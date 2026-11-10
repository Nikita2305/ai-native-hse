import test from 'node:test';
import assert from 'node:assert/strict';
import {mailPayload, initValue, isoDate, calendarRecords, attachmentParams} from '../scripts/browser/web-readonly.mjs';

test('mail API rejects writes, including mixed read/write batches', () => {
  for (const models of [[{name:'do-messages'}], [{name:'messages'}, {name:'do-mail-reset-recent-counter'}]])
    assert.throws(() => mailPayload('private', '1', models), /READ_ONLY_MODEL_REJECTED/);
  assert.equal(mailPayload('private', '1', [{name:'message-body'}]).models[0].name, 'message-body');
});

test('mail bootstrap decodes JSON escaped token characters', () => {
  assert.equal(initValue('{"_ckey":"a\\u002Fb\\\"c"}', '_ckey'), 'a/b"c');
  assert.throws(() => initValue('<title>Login</title>', '_ckey'), /SESSION_REFRESH_REQUIRED/);
});

test('calendar windows exclude adjacent weeks, retain simultaneous courses and Moscow timezone', () => {
  const lesson = {name:'Course A',begin_time:'18:10',end_time:'19:30'};
  const days = [{date:'2026-10-31',lessons:[lesson]}, {date:'2026-11-02',lessons:[lesson, {...lesson,name:'Course B'}]}];
  const rows=calendarRecords([...days, days[1]], '2026-11-01', '2026-11-03');
  assert.equal(rows.length,2);
  assert.notEqual(rows[0].id,rows[1].id);
  assert.equal(rows[0].start,'2026-11-02T18:10:00+03:00');
  assert.equal(new Date(rows[0].start).toISOString(),'2026-11-02T15:10:00.000Z');
  assert.throws(() => isoDate('2026-02-30'), /INVALID_DATE/);
});

test('attachment download rejects path traversal and non-message identifiers', () => {
  for (const name of ['../private', 'a/b.docx', 'a\\b.docx', '\u0000.docx'])
    assert.throws(() => attachmentParams({mid:'123',hid:'1.2',name}), /INVALID_ATTACHMENT/);
  assert.throws(() => attachmentParams({mid:'https://other',hid:'1.2',name:'a.docx'}), /INVALID_ATTACHMENT/);
  assert.equal(attachmentParams({mid:'123',hid:'1.2',name:'ИЗ.docx'}).name, 'ИЗ.docx');
});

// Exercise an authenticated read end-to-end against a synthetic mailbox.
import {mailSync} from '../scripts/browser/web-readonly.mjs';
function fakeMailbox(messages, changeFlags = false) {
  const operations=[];
  let listingCalls=0;
  const client={
    async get() {return {status:()=>200,text:async()=>' {"_ckey":"fixture","_uid":"1"} '};},
    async post(url,options) {
      const model=options.data.models[0];operations.push(model.name);
      let data;
      if(model.name==='get-user-emails')data={userEmails:[{login:'student',domain:'example.org'}]};
      else if(model.name==='folders')data={folder:[],new:1};
      else if(model.name==='messages') {
        listingCalls++;
        data={message:messages.map(m=>({...m,new:changeFlags&&listingCalls>1?false:m.new})),details:{'has-more':false}};
      } else if(model.name==='message-body')data={body:[{type:'text',content:'Synthetic message body'}]};
      else throw new Error('Unexpected write model: '+model.name);
      return {status:()=>200,json:async()=>({models:[{name:model.name,status:'ok',data}]})};
    },
  };
  return {client,operations};
}
const sampleMail=(mid,date)=>({mid,subject:'Example',date:{timestamp:Date.parse(date)},new:true});

test('mail limit remains partial when the same page also contains older mail',async()=>{
  const {client,operations}=fakeMailbox([
    sampleMail('1','2030-09-03T10:00:00Z'),sampleMail('2','2030-09-02T10:00:00Z'),
    sampleMail('3','2030-08-30T10:00:00Z'),
  ]);
  const writes=new Map();
  const result=await mailSync(client,{action:'sync',since:'2030-09-01',limit:1},
    (name,data)=>{writes.set(name,data);return name;});
  assert.equal(result.retrieved,1);
  assert.deepEqual(result.account,["student@example.org"]);
  assert.equal(result.limited,true);
  assert.equal(result.selected_unread_flags_unchanged,true);
  assert.equal(writes.get('mail-records.json')[0].unread,true);
  assert.ok(operations.every(name=>['get-user-emails','folders','messages','message-body'].includes(name)));
});

test('mail stops without claiming truncation if every matching message was read',async()=>{
  const {client}=fakeMailbox([sampleMail('1','2030-09-03T10:00:00Z')]);
  const result=await mailSync(client,{action:'sync',since:'2030-09-01',limit:1},()=>'/synthetic');
  assert.equal(result.limited,false);
});

test('mail refuses a result when individual read flags changed despite a stable counter',async()=>{
  const {client}=fakeMailbox([sampleMail('1','2030-09-03T10:00:00Z')],true);
  let wrote=false;
  await assert.rejects(mailSync(client,{action:'sync',since:'2030-09-01',limit:1},()=>{wrote=true;}),/MAIL_FLAGS_CHANGED_DURING_READ/);
  assert.equal(wrote,false);
});

test('mail respects an explicit upper date as well as the lower date',async()=>{
 const {client}=fakeMailbox([sampleMail('1','2030-10-02T10:00:00Z'),sampleMail('2','2030-09-03T10:00:00Z')]);
 const saved=new Map();
 const result=await mailSync(client,{action:'sync',since:'2030-09-01',until:'2030-09-30',limit:10},(name,value)=>{saved.set(name,value);return name;});
 assert.equal(result.retrieved,1);
 assert.equal(saved.get('mail-records.json')[0].id,'mail:web:2');
});

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {login,fillLogin,credentialsFromFile,ssoCookies} from '../scripts/browser/login.mjs';

test('headless login reuses a valid session, verifies access, and saves private state',async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'hse-login-test-'));
 let launchOptions,closed=false,opened=false;
 const state={cookies:[],origins:[{origin:'https://lk.hse.ru',localStorage:[{name:'access_token',value:'fixture'}]}]};
 const context={request:{get:async()=>({status:()=>200,json:async()=>({id:'fixture'})})},storageState:async()=>state,newPage:async()=>{opened=true;throw new Error('Unnecessary login page');}};
 try {
  const result=await login({source:'calendar',dataDir:folder,launch:async options=>{launchOptions=options;return {newContext:async()=>context,close:async()=>{closed=true;}};}});
  assert.equal(launchOptions.headless,true);assert.equal(opened,false);assert.equal(closed,true);
  assert.equal(result.session_saved,true);
  const file=path.join(folder,'auth/browser/state.json');
  assert.deepEqual(JSON.parse(fs.readFileSync(file)),state);
  assert.equal(fs.statSync(file).mode&0o777,0o600);
 }finally{fs.rmSync(folder,{recursive:true,force:true});}
});

test('failed unattended login closes browser and preserves previous state',async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'hse-login-test-'));
 const file=path.join(folder,'auth/browser/state.json');fs.mkdirSync(path.dirname(file),{recursive:true});
 const previous=JSON.stringify({cookies:[],origins:[]});fs.writeFileSync(file,previous);
 let closed=false;
 const page={url:()=> 'https://saml.hse.ru/mfa',goto:async()=>{},isClosed:()=>false,waitForLoadState:async()=>{}};
 const context={storageState:async()=>({cookies:[],origins:[]}),route:async()=>{},newPage:async()=>page,pages:()=>[page]};
 try {
  await assert.rejects(login({source:'calendar',dataDir:folder,launch:async()=>({newContext:async()=>context,close:async()=>{closed=true;}})}),/LOGIN_INTERACTION_REQUIRED/);
  assert.equal(closed,true);assert.equal(fs.readFileSync(file,'utf8'),previous);
 }finally{fs.rmSync(folder,{recursive:true,force:true});}
});

test('login fills HSE credentials only at trusted SSO origins',async()=>{
 const filled=[];
 const field={first(){return this;},isVisible:async()=>true,fill:async value=>filled.push(value),click:async()=>{}};
 const credentials={username:'student@example.org',password:'synthetic-password'};
 const page={url:()=> 'https://example.org/fake-login',locator:()=>field,getByRole:()=>field};
 assert.equal(await fillLogin(page,credentials),false);assert.deepEqual(filled,[]);
 page.url=()=> 'http://saml.hse.ru/login';
 assert.equal(await fillLogin(page,credentials),false);assert.deepEqual(filled,[]);
 page.url=()=> 'https://saml.hse.ru/login';
 assert.equal(await fillLogin(page,credentials),true);assert.deepEqual(filled,[credentials.username,credentials.password]);
 filled.length=0;page.url=()=> 'https://passport.yandex.com/auth';
 assert.equal(await fillLogin(page,credentials),true);assert.deepEqual(filled,[credentials.username]);
});

test('SSO import includes only auth domains and credentials require explicit JSON fields',()=>{
 const cookies=ssoCookies('saml.hse.ru\tFALSE\t/\tTRUE\t0\tfixture\tvalue\nexample.org\tFALSE\t/\tTRUE\t0\tother\tvalue');
 assert.equal(cookies.length,1);assert.equal(cookies[0].domain,'saml.hse.ru');
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'hse-login-test-'));
 try{
  const file=path.join(folder,'credentials.json');fs.writeFileSync(file,'{"password":"fixture"}');
  assert.throws(()=>credentialsFromFile(file),/LOGIN_USERNAME_AND_PASSWORD_REQUIRED/);
  fs.writeFileSync(file,'bare-password');assert.throws(()=>credentialsFromFile(file),/LOGIN_CREDENTIALS_JSON_REQUIRED/);
 }finally{fs.rmSync(folder,{recursive:true,force:true});}
});

test('mail uses absolute timezone-aware bounds and stops at now, not midnight',async()=>{
 const lower=Date.parse('2030-09-01T00:00:00-04:00');
 const upper=Date.parse('2030-09-03T12:34:56.124Z');
 const {client}=fakeMailbox([
  sampleMail('1','2030-09-03T15:00:00Z'),
  sampleMail('2','2030-09-03T12:34:56.124Z'),
  sampleMail('3','2030-09-03T12:34:56.123Z'),
  sampleMail('4','2030-09-01T04:00:00Z'),
  sampleMail('5','2030-09-01T03:59:59.999Z'),
 ]);
 const saved=new Map();
 const result=await mailSync(client,{action:'sync',since:'2030-09-01',until:'2030-09-03','since-ms':String(lower),'until-ms':String(upper),limit:10},(name,value)=>{saved.set(name,value);return name;});
 assert.deepEqual(saved.get('mail-records.json').map(r=>r.id),['mail:web:3','mail:web:4']);
 assert.equal(result.since_instant,new Date(lower).toISOString());
 assert.equal(result.until_exclusive,new Date(upper).toISOString());
});
