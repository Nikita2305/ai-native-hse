// Read mail and timetable through the user's existing authenticated web sessions.
// No mailbox UI is loaded: its automatic counter updates would violate read only.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {request, chromium} from 'playwright';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const dataDir = path.resolve(process.env.HSE_DATA_DIR || path.join(project, 'data'));
const build = process.env.HSE_WORK_DIR;
const statePath = path.join(dataDir, 'auth', 'browser', 'state.json');
const mailOrigin = 'https://mail.360.yandex.com';
const elkOrigin = 'https://lk.hse.ru';
// Selects the full web client response instead of the legacy HTML-only client.
export const userAgent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/145.0.0.0 Safari/537.36';
const allowedModels = new Set(['folders', 'messages', 'message-body', 'get-user-emails']);
const allowedElk = new Set(['/api/get-user', '/api/get-academic-data', '/api/get-myschedule']);
const hash = value => createHash('sha256').update(value).digest('hex');
const now = () => new Date().toISOString();

export function mailPayload(ckey, uid, models) {
  if (!models.length || models.some(m => !allowedModels.has(m.name))) throw new Error('READ_ONLY_MODEL_REJECTED');
  return {_ckey: ckey, _uid: uid, models};
}

export function initValue(html, key) {
  const match = html.match(new RegExp('"' + key + '"\\s*:\\s*("(?:\\\\.|[^"\\\\])*")'));
  if (!match) throw new Error('MAIL_SESSION_REFRESH_REQUIRED');
  return JSON.parse(match[1]);
}

export function isoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '') || new Date(value).toISOString().slice(0, 10) !== value)
    throw new Error('INVALID_DATE');
  return value;
}

function write(name, data) {
  const target = path.join(build, name);
  fs.mkdirSync(path.dirname(target), {recursive: true});
  fs.writeFileSync(target, JSON.stringify(data, null, 2), {mode: 0o600});
  return target;
}

async function jsonResponse(response, label) {
  if (response.status() !== 200) throw new Error(label + '_HTTP_' + response.status());
  try { return await response.json(); } catch { throw new Error(label + '_NON_JSON'); }
}

async function mailAuth(client) {
  const response = await client.get(mailOrigin + '/', {maxRedirects: 0});
  if (response.status() !== 200) throw new Error('MAIL_SESSION_REFRESH_REQUIRED');
  const html = await response.text();
  const ckey = initValue(html, '_ckey'), uid = initValue(html, '_uid');
  const call = async (name, params = {}) => {
    const response = await client.post(mailOrigin + '/web-api/models/liza1', {
      data: mailPayload(ckey, uid, [{name, params}]), maxRedirects: 0,
    });
    const data = await jsonResponse(response, 'MAIL');
    const model = data.models?.find(m => m.name === name);
    if (model?.status !== 'ok') throw new Error('MAIL_MODEL_REJECTED');
    return model.data;
  };
  const emails = await call('get-user-emails', {mailboxUid: null});
  if (!emails.userEmails?.length) throw new Error('MAIL_ACCOUNT_UNAVAILABLE');
  call.account = emails.userEmails.map(e => `${e.login}@${e.domain}`);
  return call;
}

export async function mailSync(client, options, writeOutput = write) {
  const call = await mailAuth(client);
  // readOnly here controls the web client's folder visibility (e.g. Sent/Drafts),
  // not permission to modify messages. The folders model only returns metadata.
  const folderParams = {mailboxUid: null, isPop3: false, readOnly: false};
  const before = await call('folders', folderParams);
  if (options.action === 'folders') return {account: call.account, folders: before.folder, unread: before.new};
  const since = isoDate(options.since);
  const cutoff = new Date(since + 'T00:00:00+03:00').getTime();
  const through = options.until ? isoDate(options.until) : null;
  if (through && through < since) throw new Error('INVALID_MAIL_RANGE');
  const upper = through ? new Date(through + 'T00:00:00+03:00').getTime() + 86400000 : Infinity;
  const limit = Number(options.limit || 100), folder = String(options.folder || '1');
  if (!Number.isInteger(limit) || limit < 1 || limit > 500 || !/^\d+$/.test(folder)) throw new Error('INVALID_MAIL_LIMIT_OR_FOLDER');
  const selected = [], seen = new Set();
  let first = 0, more = true, reachedCutoff = false, omittedMatching = false;
  const list = offset => call('messages', {mailboxUid: null, current_folder: folder,
    sort_type: 'date', first: offset, count: 100, with_pins: 'no'});
  while (more && selected.length < limit) {
    const data = await list(first), messages = data.message || [];
    if (!Array.isArray(messages)) throw new Error('MAIL_SCHEMA_CHANGED');
    let added = 0;
    for (const msg of messages) {
      if (seen.has(msg.mid)) continue;
      seen.add(msg.mid); added++;
      if (msg.date.timestamp >= upper) continue;
      if (msg.date.timestamp < cutoff) { reachedCutoff = true; continue; }
      if (selected.length < limit) selected.push(msg); else omittedMatching = true;
    }
    more = Boolean(data.details?.['has-more']); first += messages.length;
    if (reachedCutoff || !messages.length) break;
    if (!added) throw new Error('MAIL_PAGINATION_NOT_ADVANCING');
  }
  const records = [], originals = [];
  for (const msg of selected) {
    const data = await call('message-body', {ids: msg.mid, draft: 'false', raw: 'false', is_spam: 'false', mailboxUid: null});
    if (!Array.isArray(data.body)) throw new Error('MAIL_BODY_SCHEMA_CHANGED');
    originals.push({mid: msg.mid, data});
    records.push({id: 'mail:web:' + msg.mid, source: 'mail', course: null,
      title: msg.subject || '(Без темы)', source_date: new Date(msg.date.timestamp).toISOString(),
      retrieved_at: now(), url: mailOrigin + '/#message/' + msg.mid,
      sender: msg.field?.filter(f => f.type === 'from').map(f => ({name: f.name, email: f.email})),
      unread: Boolean(msg.new), body_parts: data.body, attachments: data.attachment || [],
      text: '', coverage: 'full web API body; attachments listed, not downloaded'});
  }
  const after = await call('folders', folderParams);
  const flagsAfter = new Map();
  for (let offset = 0; offset < first; offset += 100) {
    for (const m of (await list(offset)).message || []) flagsAfter.set(m.mid, Boolean(m.new));
  }
  const changed = selected.filter(m => !flagsAfter.has(m.mid) || flagsAfter.get(m.mid) !== Boolean(m.new));
  if (changed.length) throw new Error('MAIL_FLAGS_CHANGED_DURING_READ');
  writeOutput('mail-bodies.json', originals);
  const recordsFile = writeOutput('mail-records.json', records);
  const result = {account: call.account, records_file: recordsFile, retrieved: records.length, folder, since,
    limited: omittedMatching || (selected.length === limit && more && !reachedCutoff),
    unread_before: before.new, unread_after: after.new, selected_unread_flags_unchanged: true};
  writeOutput('mail-coverage.json', result);
  return result;
}

export function attachmentParams(options) {
  if (!/^\d+$/.test(options.mid || '') || !/^\d+(?:\.\d+)*$/.test(options.hid || '') ||
      !options.name || options.name.length > 240 || /[\\/\x00-\x1f]/.test(options.name)) throw new Error('INVALID_ATTACHMENT');
  return {mid: options.mid, hid: options.hid, name: options.name};
}

async function mailAttachment(client, options) {
  const {mid,hid,name} = attachmentParams(options);
  const call = await mailAuth(client);
  const params={mailboxUid:null,isPop3:false,readOnly:false};
  const before=await call('folders',params);
  const root=await client.get(mailOrigin+'/');
  const uid=initValue(await root.text(),'_uid');
  const response=await client.get(mailOrigin+'/message_part/'+encodeURIComponent(name),
    {params:{_uid:uid,name,hid,ids:mid},maxRedirects:5});
  if(response.status()!==200)throw new Error('MAIL_ATTACHMENT_HTTP_'+response.status());
  const body=await response.body();
  if(body.length>25*1024*1024)throw new Error('MAIL_ATTACHMENT_TOO_LARGE');
  const target=path.join(build,'attachments',mid+'-'+hid+'-'+name);
  fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,body,{mode:0o600});
  const after=await call('folders',params);
  if(before.new!==after.new)throw new Error('MAIL_UNREAD_COUNTER_CHANGED_DURING_READ');
  return {mid,hid,name,content_base64:body.toString('base64'),bytes:body.length,unread_before:before.new,unread_after:after.new};
}

async function elkGet(client, state, endpoint, query = {}) {
  if (!allowedElk.has(endpoint)) throw new Error('READ_ONLY_ENDPOINT_REJECTED');
  const token = state.origins?.find(o => o.origin === elkOrigin)?.localStorage?.find(i => i.name === 'access_token')?.value;
  if (!token) throw new Error('ELK_SESSION_REFRESH_REQUIRED');
  const response = await client.get(elkOrigin + endpoint, {params: query,
    headers: {Authorization: 'Bearer ' + token}, maxRedirects: 0});
  return jsonResponse(response, 'ELK');
}

export function calendarRecords(days, since, until) {
  const records = [];
  for (const day of days) {
    isoDate(day.date);
    if (day.date < since || day.date > until) continue;
    if (!Array.isArray(day.lessons)) throw new Error('CALENDAR_SCHEMA_CHANGED');
    for (const lesson of day.lessons) {
      if (![lesson.begin_time, lesson.end_time].every(t => /^\d{2}:\d{2}$/.test(t))) throw new Error('CALENDAR_TIME_INVALID');
      const start = `${day.date}T${lesson.begin_time}:00+03:00`;
      const end = `${day.date}T${lesson.end_time}:00+03:00`;
      const identity = JSON.stringify([day.date, lesson]);
      records.push({id: 'calendar:elk:' + hash(identity), source: 'calendar', course: null,
        title: lesson.name, source_date: start, start, end, timezone: 'Europe/Moscow',
        retrieved_at: now(), url: elkOrigin + '/schedule?begin_date=' + day.date,
        text: JSON.stringify(lesson), lesson, coverage: 'personal ELK timetable, not Moodle deadlines'});
    }
  }
  return [...new Map(records.map(r => [r.id, r])).values()];
}

async function calendarSync(client, state, options) {
  const since = isoDate(options.since), until = isoDate(options.until);
  if (until < since || new Date(until) - new Date(since) > 180 * 86400000) throw new Error('INVALID_CALENDAR_RANGE');
  const date = new Date(since + 'T00:00:00Z');
  date.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7);
  const weeks = [];
  while (date.toISOString().slice(0, 10) <= until) {
    const week = date.toISOString().slice(0, 10);
    const days = await elkGet(client, state, '/api/get-myschedule', {begin_date: week});
    if (!Array.isArray(days)) throw new Error('CALENDAR_SCHEMA_CHANGED');
    weeks.push({week, days}); date.setUTCDate(date.getUTCDate() + 7);
  }
  write('calendar-weeks.json', weeks);
  const records = calendarRecords(weeks.flatMap(w => w.days), since, until);
  const recordsFile = write('calendar-records.json', records);
  return {records_file: recordsFile, retrieved: records.length, weeks: weeks.length,
    since, until, subjects: [...new Set(records.map(r => r.title))]};
}

async function refreshSession(state) {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const context = await browser.newContext({storageState: state});
    const jar = path.join(dataDir, 'auth/lms/cookies.txt');
    if (fs.existsSync(jar)) await context.addCookies(fs.readFileSync(jar, 'utf8').split('\n').flatMap(line => {
      if (line.startsWith('#HttpOnly_')) line = line.slice(10);
      if (!line || line.startsWith('#')) return [];
      const [domain, , cookiePath, secure, expires, name, value] = line.split('\t');
      return domain === 'saml.hse.ru' ? [{domain, path: cookiePath, secure: secure === 'TRUE', name, value,
        ...(Number(expires) > 0 ? {expires: Number(expires)} : {})}] : [];
    }));
    // Refresh ELK's own SSO/token. Do not open the mailbox UI.
    const page = await context.newPage();
    await page.route('https://lk.hse.ru/**', route => route.request().method() === 'GET' ? route.continue() : route.abort());
    await page.goto(elkOrigin + '/schedule', {waitUntil: 'domcontentloaded', timeout: 45000});
    await page.waitForLoadState('networkidle', {timeout: 20000}).catch(() => {});
    await page.waitForFunction(() => Boolean(localStorage.getItem('access_token')), {timeout: 30000});
    const next = await context.storageState();
    const client = await request.newContext({storageState: next, userAgent});
    try { await elkGet(client, next, '/api/get-user'); } finally { await client.dispose(); }
    fs.mkdirSync(path.dirname(statePath), {recursive:true});
    fs.writeFileSync(statePath, JSON.stringify(next), {mode:0o600});
    return {session_refreshed: true};
  } finally { await browser.close(); }
}

async function main() {
  process.umask(0o077);
  const [command, action, ...rest] = process.argv.slice(2);
  const options = {action};
  for (let i = 0; i < rest.length; i += 2) {
    if (!['--since', '--until', '--limit', '--folder', '--mid', '--hid', '--name'].includes(rest[i]) || !rest[i + 1]) throw new Error('INVALID_OPTION');
    options[rest[i].slice(2)] = rest[i + 1];
  }
  const seed = statePath;
  if (!fs.existsSync(seed)) throw new Error('WEB_SESSION_NOT_CONFIGURED');
  const state = JSON.parse(fs.readFileSync(seed, 'utf8'));
  if (command === 'refresh-session') return refreshSession(state);
  const client = await request.newContext({storageState: state, userAgent, timeout: 30000});
  try {
    let result;
    if (command === 'mail' && ['folders', 'sync'].includes(action)) result = await mailSync(client, options);
    else if (command === 'mail' && action === 'attachment') result = await mailAttachment(client, options);
    else if (command === 'calendar' && action === 'sync') result = await calendarSync(client, state, options);
    else if (command === 'calendar' && action === 'profile') {
      const data = await elkGet(client, state, '/api/get-academic-data');
      result = {profile: data};
    } else throw new Error('UNSUPPORTED_COMMAND');
    // RequestContext updates cookies but has no localStorage; keep ELK tokens.
    const cookies = await client.storageState();
    fs.writeFileSync(statePath, JSON.stringify({...state, cookies: cookies.cookies}), {mode:0o600});
    if (result.records_file) {
      result.records = JSON.parse(fs.readFileSync(result.records_file, 'utf8'));
      delete result.records_file;
    }
    return result;
  } finally { await client.dispose(); }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then(result => console.log(JSON.stringify(result))).catch(error => {
    console.error(/^[A-Z0-9_]+$/.test(error.message) ? error.message : 'WEB_SOURCE_REQUEST_FAILED');
    process.exitCode = 1;
  });
}
