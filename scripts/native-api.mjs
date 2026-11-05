// LOCAL disposable database only. No cloud connection strings are read.
import EmbeddedPostgres from 'embedded-postgres';
import pg from 'pg';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { createServer } from 'node:net';
import { spawn } from 'node:child_process';
const root=fileURLToPath(new URL('..',import.meta.url));
const port=await new Promise((done,fail)=>{const s=createServer();s.once('error',fail);s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>done(p));});});
const dir=await mkdtemp(resolve(tmpdir(),'invoice-api-pg-'));
const password=randomUUID();
const cluster=new EmbeddedPostgres({databaseDir:dir,user:'postgres',password,port,persistent:false,
 createPostgresUser:false,autoRehydrateSymlinks:true,initdbFlags:['--locale=C','--encoding=UTF8'],
 postgresFlags:['-h','127.0.0.1','-k',''],onLog:()=>{},onError:()=>{}});
let client;
try {
 await cluster.initialise();await cluster.start();
 client=new pg.Client({host:'127.0.0.1',port,user:'postgres',password,database:'postgres'});await client.connect();
 await client.query(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;
 CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);`);
 await client.query(await readFile(resolve(root,'migrations/schema.sql'),'utf8'));
 await client.query(await readFile(resolve(root,'migrations/step3.sql'),'utf8'));
 await client.query(`INSERT INTO auth.users VALUES('11111111-1111-4111-8111-111111111111'),('22222222-2222-4222-8222-222222222222');
 INSERT INTO app.profiles(user_id,display_name,role) VALUES
 ('11111111-1111-4111-8111-111111111111','Native test admin','admin'),
 ('22222222-2222-4222-8222-222222222222','Native test user','user');`);
 const code=await new Promise((done,fail)=>{const p=spawn(resolve(root,'.venv/bin/python'),['-m','pytest','tests/test_native.py','tests/test_pipeline_native.py','-q'],
 {cwd:root,stdio:'inherit',env:{...process.env,INVOICE_TEST_ISOLATED:'1',INVOICE_TEST_DATABASE_URL:`postgresql://postgres:${password}@127.0.0.1:${port}/postgres`}});
 p.on('error',fail);p.on('exit',done);});
 process.exitCode=code;
} finally {if(client) await client.end();await cluster.stop().catch(()=>{});await rm(dir,{recursive:true,force:true});}

