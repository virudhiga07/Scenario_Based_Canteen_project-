// Local preview/test adapter for D1's prepared-statement interface; production uses D1 directly.
import {DatabaseSync} from 'node:sqlite';
export function openDatabase(filename,schema){
 const sql=new DatabaseSync(filename);sql.exec('PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL;');if(schema)sql.exec(schema);
 let tail=Promise.resolve();
 const db={prepare(query){const stmt=sql.prepare(query);const make=(args=[])=>({bind(...args){return make(args)},async first(){return stmt.get(...args)??null},async all(){return {results:stmt.all(...args)}},async run(){return {meta:stmt.run(...args)}}});return make()},batch(statements){const job=tail.then(async()=>{sql.exec('BEGIN IMMEDIATE');try{const result=[];for(const s of statements)result.push(await s.run());sql.exec('COMMIT');return result}catch(e){sql.exec('ROLLBACK');throw e}});tail=job.catch(()=>{});return job},close(){sql.close()}};return db;
}
