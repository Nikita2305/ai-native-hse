// Interactive authentication only; mailbox pages are never opened.
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline/promises';
import {chromium} from 'playwright';
process.umask(0o077);
const source=process.argv[2];
if(!['mail','calendar'].includes(source)) throw new Error('INVALID_SOURCE');
const statePath=path.join(process.env.HSE_DATA_DIR,'auth/browser/state.json');
const browser=await chromium.launch({headless:false});
try {
 const context=await browser.newContext(fs.existsSync(statePath)?{storageState:statePath}:{});
 const page=await context.newPage();
 // Block mailbox UI: it can automatically change counters and read state.
 await context.route(/https:\/\/(?:mail\.yandex\.(?:ru|com)|mail\.360\.yandex\.com)\//,route=>route.abort());
 await page.goto(source==='mail'?'https://passport.yandex.com/auth?retpath=https%3A%2F%2Fpassport.yandex.com%2Fprofile':'https://lk.hse.ru/schedule');
 const terminal=readline.createInterface({input:process.stdin,output:process.stdout});
 await terminal.question('Complete login in the browser, then press Enter here. '); terminal.close();
 fs.mkdirSync(path.dirname(statePath),{recursive:true});
 await context.storageState({path:statePath}); fs.chmodSync(statePath,0o600);
 console.log('Session saved. Run doctor --online to validate access.');
} finally {await browser.close();}
