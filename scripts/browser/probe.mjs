import fs from 'node:fs';
import path from 'node:path';
import {request} from 'playwright';
import {initValue,mailPayload,userAgent} from './web-readonly.mjs';
const data=process.env.HSE_DATA_DIR;
const state=JSON.parse(fs.readFileSync(path.join(data,'auth/browser/state.json')));
const client=await request.newContext({storageState:state,userAgent,timeout:25000});
const result={};
try {
 try {
  const root=await client.get('https://mail.360.yandex.com/',{maxRedirects:0});
  if(root.status()!==200)throw new Error();
  const html=await root.text();
  const response=await client.post('https://mail.360.yandex.com/web-api/models/liza1',{data:mailPayload(initValue(html,'_ckey'),initValue(html,'_uid'),[{name:'get-user-emails',params:{mailboxUid:null}}]),maxRedirects:0});
  const model=(await response.json()).models?.find(m=>m.name==='get-user-emails');
  result.mail=model?.status==='ok'&&model.data.userEmails?.length?'ok':'session_invalid';
 }catch{result.mail='session_invalid';}
 try {
  const token=state.origins?.find(o=>o.origin==='https://lk.hse.ru')?.localStorage?.find(x=>x.name==='access_token')?.value;
  if(!token)throw new Error();
  const response=await client.get('https://lk.hse.ru/api/get-user',{headers:{Authorization:'Bearer '+token},maxRedirects:0});
  const body=await response.json();result.calendar=response.status()===200&&body?'ok':'session_invalid';
 }catch{result.calendar='session_invalid';}
 console.log(JSON.stringify(result));
}finally{await client.dispose();}
