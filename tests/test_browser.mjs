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
