// Authentication only. Source content is never opened by the browser UI.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import readline from 'node:readline/promises';
import {chromium} from 'playwright';
import {mailAuth, elkGet, userAgent} from './web-readonly.mjs';

export function credentialsFromFile(filename) {
  if (!filename) return null;
  let value;
  try { value = JSON.parse(fs.readFileSync(filename, 'utf8')); }
  catch { throw new Error('LOGIN_CREDENTIALS_JSON_REQUIRED'); }
  if (!value || !['username','password'].every(k => typeof value[k] === 'string' && value[k].trim()))
    throw new Error('LOGIN_USERNAME_AND_PASSWORD_REQUIRED');
  return value;
}

export function ssoCookies(text) {
  return text.split('\n').flatMap(line => {
    const httpOnly = line.startsWith('#HttpOnly_');
    if (httpOnly) line = line.slice(10);
    if (!line || line.startsWith('#')) return [];
    const [domain, , cookiePath, secure, expires, name, value] = line.split('\t');
    if (!['saml.hse.ru','idm.hse.ru'].includes(domain) || !name) return [];
    return [{domain,path:cookiePath,secure:secure==='TRUE',httpOnly,name,value,
      ...(Number(expires)>0?{expires:Number(expires)}:{})}];
  });
}

export async function fillLogin(page, credentials) {
  if (!credentials) return false;
  const location = new URL(page.url());
  if (location.protocol !== 'https:') return false;
  const host = location.hostname;
  if (/^passport\.yandex\.(com|ru)$/.test(host)) {
    const login=page.locator('input[name="login"], input[autocomplete="username"]').first();
    if (await login.isVisible()) {
      await login.fill(credentials.username);
      await page.getByRole('button',{name:/войти|log in|sign in|далее|next/i}).first().click();
      return true;
    }
  } else if (['saml.hse.ru','idm.hse.ru'].includes(host)) {
    const username=page.locator('input[name="username"]').first();
    const password=page.locator('input[name="password"]').first();
    if (await username.isVisible() && await password.isVisible()) {
      await username.fill(credentials.username);
      await password.fill(credentials.password);
      await page.locator('input[type="submit"], button[type="submit"]').first().click();
      return true;
    }
  }
  return false;
}

async function validate(context, source) {
  if (source==='mail') {
    const call=await mailAuth(context.request);
    return {account:call.account};
  }
  await elkGet(context.request,await context.storageState(),'/api/get-user');
  return {};
}

export async function login({source,dataDir,secretFile,interactive=false,launch=options=>chromium.launch(options)}) {
  if (!['mail','calendar'].includes(source)) throw new Error('INVALID_SOURCE');
  const credentials=credentialsFromFile(secretFile);
  const statePath=path.join(dataDir,'auth/browser/state.json');
  const browser=await launch({headless:!interactive,args:process.getuid?.()===0?['--no-sandbox']:[]});
  try {
    const context=await browser.newContext({userAgent,...(fs.existsSync(statePath)?{storageState:statePath}:{})});
    const jar=path.join(dataDir,'auth/lms/cookies.txt');
    if (fs.existsSync(jar)) await context.addCookies(ssoCookies(fs.readFileSync(jar,'utf8')));
    const check=async()=>{
      const details=await validate(context,source);
      if(source==='mail' && credentials?.username.includes('@') && !details.account.some(address=>address.toLowerCase()===credentials.username.toLowerCase()))
        throw new Error('LOGIN_ACCOUNT_MISMATCH');
      return details;
    };
    const persist=async details=>{
      const state=await context.storageState();
      fs.mkdirSync(path.dirname(statePath),{recursive:true,mode:0o700});
      const next=statePath+'.tmp';
      fs.writeFileSync(next,JSON.stringify(state),{mode:0o600});
      fs.chmodSync(next,0o600);
      fs.renameSync(next,statePath);
      return {session_saved:true,source,interactive,...details};
    };
    // A valid existing session requires neither credentials nor a browser page.
    try { const details=await check(); return await persist(details); } catch {}
    // Prevent loading mailbox scripts/counters, including after login redirects.
    await context.route(/https:\/\/(?:mail\.yandex\.(?:ru|com)|mail\.360\.yandex\.com)\//,
      route=>route.fulfill({status:200,contentType:'text/html',body:'Authentication complete'}));
    await context.route('https://lk.hse.ru/**',route=>route.request().method()==='GET'?route.continue():route.abort());
    const page=await context.newPage();
    await page.goto(source==='mail'
      ?'https://passport.yandex.com/auth?retpath=https%3A%2F%2Fmail.yandex.com%2F'
      :'https://lk.hse.ru/schedule',{waitUntil:'domcontentloaded',timeout:45000});
    const submitted=new Set();
    for (let attempt=0;attempt<4;attempt++) {
      for (const tab of context.pages()) {
        if (tab.isClosed()) continue;
        await tab.waitForLoadState('networkidle',{timeout:10000}).catch(()=>{});
        const host=new URL(tab.url()).hostname;
        if(!submitted.has(host) && await fillLogin(tab,credentials)) submitted.add(host);
        await tab.waitForLoadState('networkidle',{timeout:10000}).catch(()=>{});
      }
      try { const details=await check(); return await persist(details); } catch {}
    }
    if (!interactive) throw new Error('LOGIN_INTERACTION_REQUIRED');
    const terminal=readline.createInterface({input:process.stdin,output:process.stdout});
    try { await terminal.question('Complete authentication in the browser, then press Enter. '); }
    finally { terminal.close(); }
    const details=await check();
    return await persist(details);
  } finally { await browser.close(); }
}

if (process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  process.umask(0o077);
  const [source,...args]=process.argv.slice(2);
  const interactive=args.includes('--interactive');
  const index=args.indexOf('--secret-file');
  const secretFile=index>=0?args[index+1]:null;
  login({source,dataDir:process.env.HSE_DATA_DIR,secretFile,interactive})
    .then(value=>console.log(JSON.stringify(value)))
    .catch(error=>{console.error(/^[A-Z_]+$/.test(error.message)?error.message:'BROWSER_LOGIN_FAILED');process.exitCode=1;});
}
