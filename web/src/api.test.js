import test from "node:test";
import assert from "node:assert/strict";
import { apiRequest } from "./api.js";
const json = (data, status=200) => new Response(JSON.stringify(data), { status, headers: {"content-type":"application/json"} });

test("host allocation HTML is never treated as login or upload success, including HTTP 200", async () => {
  for (const status of [200, 502, 503]) {
    let calls=0;
    await assert.rejects(apiRequest('/api/submissions', {method:'POST', body:'{}'}, {fetchImpl:async()=>{calls++;return new Response('<html>Allocating service</html>', {status,headers:{'content-type':'text/html'}})}}), /starting or temporarily unavailable/);
    assert.equal(calls,1); // Never automatically replay financial mutations.
  }
});
test("the original structured rejection keeps its status and message", async () => {
  await assert.rejects(apiRequest('/api/me', {}, {fetchImpl:async()=>json({detail:'SESSION_EXPIRED'},401)}), error=>error.status===401 && error.message==='SESSION EXPIRED');
});
test("uploads preserve multipart boundaries and the same idempotency key", async () => {
  const form=new FormData();form.append('request_key','one-stable-key');let seen;
  const result=await apiRequest('/api/submissions',{method:'POST',body:form},{fetchImpl:async(url,opts)=>{seen=opts;return json({id:'receipt'},202)}});
  assert.equal(result.id,'receipt');assert.equal(seen.body,form);assert.equal(seen.headers['Content-Type'],undefined);assert.equal(seen.credentials,'same-origin');
});
test("timeouts are bounded and explain that a free service may be waking", async () => {
  const fetchImpl=async(_,opts)=>new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError'))));
  await assert.rejects(apiRequest('/api/auth/login',{method:'POST'},{fetchImpl,timeoutMs:5}), /waking after inactivity/);
});
test("malformed or missing JSON cannot become a successful API result", async () => {
  for (const body of ['{','null','"unexpected"']) await assert.rejects(apiRequest('/api/workspace',{}, {fetchImpl:async()=>new Response(body,{headers:{'content-type':'application/json'}})}), /incomplete response|invalid response/);
});
test("timeout also bounds a stalled JSON body after headers arrived", async () => {
  const fetchImpl=async(_,opts)=>({ok:true,status:200,headers:new Headers({'content-type':'application/json'}),json:()=>new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError'))))});
  await assert.rejects(apiRequest('/api/workspace',{}, {fetchImpl,timeoutMs:5}),/took too long/);
});
