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
const sampleConfig={mail:{address:'student@example.org'}};

test('mail limit remains partial when the same page also contains older mail',async()=>{
  const {client,operations}=fakeMailbox([
    sampleMail('1','2030-09-03T10:00:00Z'),sampleMail('2','2030-09-02T10:00:00Z'),
    sampleMail('3','2030-08-30T10:00:00Z'),
  ]);
  const writes=new Map();
  const result=await mailSync(client,{action:'sync',since:'2030-09-01',limit:1},sampleConfig,
    (name,data)=>{writes.set(name,data);return name;});
  assert.equal(result.retrieved,1);
  assert.equal(result.limited,true);
  assert.equal(result.selected_unread_flags_unchanged,true);
  assert.equal(writes.get('mail-records.json')[0].unread,true);
  assert.ok(operations.every(name=>['get-user-emails','folders','messages','message-body'].includes(name)));
});

test('mail stops without claiming truncation if every matching message was read',async()=>{
  const {client}=fakeMailbox([sampleMail('1','2030-09-03T10:00:00Z')]);
  const result=await mailSync(client,{action:'sync',since:'2030-09-01',limit:1},sampleConfig,()=>'/synthetic');
  assert.equal(result.limited,false);
});

test('mail refuses a result when individual read flags changed despite a stable counter',async()=>{
  const {client}=fakeMailbox([sampleMail('1','2030-09-03T10:00:00Z')],true);
  let wrote=false;
  await assert.rejects(mailSync(client,{action:'sync',since:'2030-09-01',limit:1},sampleConfig,()=>{wrote=true;}),/MAIL_FLAGS_CHANGED_DURING_READ/);
  assert.equal(wrote,false);
});
