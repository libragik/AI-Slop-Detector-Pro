#!/usr/bin/env node
// Offline replay of the reviewed application combiner; no media or provider calls.
import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { resolve, dirname, relative } from 'node:path';
import { pathToFileURL } from 'node:url';

const ROOT = process.cwd();
const GEMINI = 'eval/runs/sightengine-temporal-screen-v2-gemini-comparison';
const SIGHT = 'eval/runs/sightengine-temporal-screen-v2';
const PRIOR_SUMMARY = 'eval/runs/sightengine-temporal-screen-v2-summary';
const OUTPUT = 'eval/runs/sightengine-temporal-screen-v2-paired-summary';
const MANIFEST = 'eval/fixtures/sightengine-temporal-screen-v2.json';
const MANIFEST_SHA = '1374a18b17699d6aef0ef0868b21f9f580bdbaa667f26caa45d92d0dcacc25b7';
const FINGERPRINT = 'e5924b9a24e01b6da7c2a09667f9122a7e8bc4bf42d097212e3bac40f74c352f';
const ADAPTER_SHA = '81656b5662ce2d9089670580527980e7e1a8d9d04e9aa8b2611e6b0d3e7ab7b3';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const assert = (ok, message) => { if (!ok) throw new Error(message); };
const read = async path => JSON.parse(await readFile(resolve(ROOT, path), 'utf8'));
const fileHash = async path => hash(await readFile(resolve(ROOT, path)));
const decision = verdict => verdict === 'No clear AI indicators' ? 'clear' : verdict === 'Inconclusive' ? 'inconclusive' :
  ['AI indicators detected', 'AI use disclosed', 'Verified AI provenance'].includes(verdict) ? 'ai' : 'technical_error';
function count(rows, key) {
  return { total: rows.length, ...Object.fromEntries(['ai', 'clear', 'inconclusive', 'technical_error'].map(value => [value, rows.filter(row => row[key] === value).length])) };
}
function percentile(values, q) {
  if (!values.length) return null;
  const ordered = [...values].sort((a,b) => a-b), at = (ordered.length - 1)*q, lo = Math.floor(at), hi = Math.ceil(at);
  return ordered[lo] + (ordered[hi]-ordered[lo])*(at-lo);
}
function parents(rows, key) {
  const groups = new Map();
  for (const row of rows) { const members = groups.get(row.parentId) || []; members.push(row); groups.set(row.parentId, members); }
  return [...groups].map(([parentId,members]) => ({ parentId, fileIds: members.map(row=>row.id),
    [key]: members.some(row=>row[key]==='technical_error') ? 'technical_error' : members.some(row=>row[key]==='ai') ? 'ai' :
      members.some(row=>row[key]==='inconclusive') ? 'inconclusive' : 'clear',
    hasAiAlert: members.some(row=>row[key]==='ai'), fileDecisions: members.map(row=>row[key]) }));
}
function summarize(rows, key) {
  const ai=rows.filter(row=>row.cohort==='publisher_assigned_ai'), neg=rows.filter(row=>row.cohort==='documented_negative'),
    known=rows.filter(row=>row.cohort==='receipt_backed_same_parent_check');
  const negativeParents=parents(neg,key);
  return { publisherAssignedAi: {...count(ai,key), byQuality: Object.fromEntries(['original','mild','severe'].map(q=>[q,count(ai.filter(row=>row.quality===q),key)])),
      nonDetectionIds: ai.filter(row=>row[key]!=='ai').map(row=>row.id), clearMissIds: ai.filter(row=>row[key]==='clear').map(row=>row.id) },
    documentedNegative: {...count(neg,key), parents:count(negativeParents,key), parentRows:negativeParents,
      falseAlertIds:neg.filter(row=>row[key]==='ai').map(row=>row.id), unresolvedIds:neg.filter(row=>row[key]==='inconclusive').map(row=>row.id)},
    sameParentReceiptedVeo:count(known,key) };
}
function referenceGates(summary, rows, key) {
  return { allCasesTechnicallyComplete: rows.every(row=>row[key]!=='technical_error'), noNegativeAiAlerts:summary.documentedNegative.ai===0,
    minimum10of12NegativeFilesClear:summary.documentedNegative.clear>=10, minimum5of6NegativeParentsClear:summary.documentedNegative.parents.clear>=5,
    minimum10of12PublisherAiDetected:summary.publisherAssignedAi.ai>=10,
    ...Object.fromEntries(Object.entries(summary.publisherAssignedAi.byQuality).map(([q,v])=>['minimum3of4PublisherAi_'+q,v.ai>=3])),
    sameParentVeoDetected:summary.sameParentReceiptedVeo.ai===1 };
}

async function main() {
  if(process.argv.length===3 && process.argv[2]==='--self-test') {
    const synthetic=[];
    for(let i=0;i<12;i++)synthetic.push({id:'ai'+i,parentId:'ai'+i,cohort:'publisher_assigned_ai',quality:['original','mild','severe'][Math.floor(i/4)],fusion:'ai'});
    for(let i=0;i<12;i++)synthetic.push({id:'neg'+i,parentId:'neg'+Math.floor(i/2),cohort:'documented_negative',quality:'original',fusion:'clear'});
    synthetic.push({id:'veo',parentId:'veo',cohort:'receipt_backed_same_parent_check',quality:'original',fusion:'ai'});
    let s=summarize(synthetic,'fusion');
    assert(Object.values(referenceGates(s,synthetic,'fusion')).every(Boolean),'Perfect synthetic gate must pass');
    assert(s.publisherAssignedAi.total===12 && s.documentedNegative.total===12 && s.documentedNegative.parents.total===6 && s.sameParentReceiptedVeo.total===1,'Cohort denominators');
    synthetic[0].fusion='inconclusive';s=summarize(synthetic,'fusion');
    assert(s.publisherAssignedAi.total===12 && s.publisherAssignedAi.ai===11 && s.publisherAssignedAi.inconclusive===1,'AI abstention retained');
    synthetic[12].fusion='inconclusive';s=summarize(synthetic,'fusion');
    assert(s.documentedNegative.parents.inconclusive===1 && s.documentedNegative.parents.clear===5,'Negative parent abstention');
    synthetic[13].fusion='ai';s=summarize(synthetic,'fusion');
    assert(s.documentedNegative.parents.ai===1 && s.documentedNegative.parents.parentRows===undefined,'Any-variant parent alert');
    synthetic[12].fusion='technical_error';s=summarize(synthetic,'fusion');
    assert(s.documentedNegative.parents.technical_error===1 && s.documentedNegative.parentRows[0].hasAiAlert,'Error precedence retains actual alert');
    assert(!referenceGates(s,synthetic,'fusion').allCasesTechnicallyComplete,'Technical failure cannot pass');
    assert(decision('Verified AI provenance')==='ai' && decision('unexpected')==='technical_error','Verdict mapping');
    console.log(JSON.stringify({status:'offline_self_tests_passed',checks:8,syntheticOnly:true,apiCalls:0}));return;
  }
  const expectedSourceSha = process.argv[2];
  assert(process.argv.length===3 && /^[a-f0-9]{64}$/.test(expectedSourceSha), 'Pass the reviewed specialist-decision.ts SHA256 as the sole argument');
  assert(await fileHash(MANIFEST)===MANIFEST_SHA,'Manifest mismatch');
  assert(await fileHash('src/lib/analyzer/specialist-decision.ts')===expectedSourceSha,'Reviewed fusion source mismatch');
  const manifest=await read(MANIFEST), gemini=await read(`${GEMINI}/receipt.json`), sight=await read(`${SIGHT}/receipt.json`);
  const verifiedSummaryReceipt=await read(`${PRIOR_SUMMARY}/receipt.json`), verifiedSight=await read(`${PRIOR_SUMMARY}/summary.json`);
  assert(await fileHash(`${SIGHT}/receipt.json`)===verifiedSummaryReceipt.sources.runReceipt.sha256,'Sightengine receipt changed after independent recomputation');
  assert(await fileHash(`${PRIOR_SUMMARY}/summary.json`)===verifiedSummaryReceipt.summarySha256,'Sightengine independently recomputed summary changed');
  assert(verifiedSummaryReceipt.savedAggregationExactlyRecomputed===true,'Missing raw aggregation verification');
  assert(gemini.manifest.sha256===MANIFEST_SHA && gemini.adapter.sha256===ADAPTER_SHA && await fileHash(`${GEMINI}/adapter.mjs`)===ADAPTER_SHA,'Gemini adapter/manifest binding mismatch');
  assert(gemini.expected.detectorFingerprint===FINGERPRINT,'Gemini fingerprint binding mismatch');
  assert(gemini.results.length===25 && sight.results.length===25 && manifest.cases.length===25,'Fixed25 denominator mismatch');
  assert(new Set(gemini.results.map(row=>row.id)).size===25 && new Set(sight.results.map(row=>row.id)).size===25,'Duplicate case identities');
  // Bundle and preserve only the pure combiner and validation schema; all imports are local or zod.
  const tsxRequire=createRequire(import.meta.resolve('tsx/package.json'));
  const build=await tsxRequire('esbuild').build({stdin:{contents:'export {applySpecialistEvidence} from "./src/lib/analyzer/specialist-decision.ts"; export {sightengineEvidenceSchema} from "./src/lib/analyzer/sightengine-types.ts";',resolveDir:ROOT,sourcefile:'offline-fusion-entry.ts',loader:'ts'},
    absWorkingDir:ROOT,bundle:true,packages:'external',platform:'node',format:'esm',target:'node22',metafile:true,write:false});
  const sources=[];
  for(const path of Object.keys(build.metafile.inputs).filter(path=>path!=='offline-fusion-entry.ts').sort())sources.push({path,sha256:await fileHash(path)});
  assert(sources.find(row=>row.path==='src/lib/analyzer/specialist-decision.ts')?.sha256===expectedSourceSha,'Source changed during bundling');
  await mkdir(resolve(ROOT,OUTPUT));
  const save=async(path,value)=>writeFile(resolve(ROOT,OUTPUT,path),JSON.stringify(value,null,2)+'\n',{flag:'wx'});
  for(const source of sources){const dest=resolve(ROOT,OUTPUT,'source',source.path);await mkdir(dirname(dest),{recursive:true});await writeFile(dest,await readFile(resolve(ROOT,source.path)),{flag:'wx'});}
  await writeFile(resolve(ROOT,OUTPUT,'fusion.mjs'),build.outputFiles[0].contents,{flag:'wx'});
  const {applySpecialistEvidence,sightengineEvidenceSchema}=await import(pathToFileURL(resolve(ROOT,OUTPUT,'fusion.mjs')).href);
  const rows=[];
  for(let index=0;index<25;index++) {
    const item=manifest.cases[index],g=gemini.results.find(row=>row.id===item.id),s=sight.results.find(row=>row.id===item.id),v=verifiedSight.cases.find(row=>row.id===item.id);
    assert(g&&s&&v&&g.mediaSha256===item.sha256&&s.mediaSha256===item.sha256&&g.index===index&&s.index===index,'Exact-byte paired identity mismatch');
    const prefix=`${String(index+1).padStart(2,'0')}-${item.id}`;
    if(g.status!=='unattempted')assert(JSON.stringify(await read(`${GEMINI}/${prefix}.json`))===JSON.stringify(g),'Gemini per-case and terminal receipt differ');
    let fused=null, geminiDecision='technical_error',fusionDecision='technical_error';
    if(g.status==='completed') {
      assert(g.result.detectorFingerprint===FINGERPRINT && g.result.model==='gemini-3.7-flash' && g.result.mediaReceipt.sha256===item.sha256,'Gemini result identity mismatch');
      assert(g.result.videoAnalysis.inspection.passes.every(pass=>pass.model==='gemini-3.7-flash'),'Gemini pass model mismatch');
      geminiDecision=decision(g.result.verdict);
      const t=s.temporal;
      const evidence=sightengineEvidenceSchema.parse({schemaVersion:1,provider:'sightengine',model:'genai',policyVersion:'sightengine-temporal-evidence-v1',policyFingerprint:t.policyFingerprint,
        status:v.technicalComplete?'complete':'limited',verdict:t.verdict,confidence:'Not calibrated',reviewRequired:t.reviewRequired,sourceSha256:item.sha256,
        samples:t.sampleRecords.map(sample=>({...sample,rawPositionMilliseconds:s.response.evidence.frames[sample.index]?.rawPositionMilliseconds??null})),persistentRuns:t.persistentRuns,isolatedAlerts:t.isolatedAlerts,
        coverage:t.coverage,technicalIssues:t.technicalIssues,decisionReasons:t.decisionReasons,failureCode:v.technicalComplete?null:'incomplete_coverage',
        request:{submissionAttempted:true,operations:v.reportedOperations,httpStatus:null,elapsedMs:s.elapsedSeconds*1000},notProofOfOrigin:true,scoresAreCalibratedProbabilities:false,adjacentSamplesAreIndependent:false});
      const fields=['baseScore','finalScore','verdict','confidence','evidenceLabel','assessmentStatus','decisionReasons','reviewRequired','adjustments'];
      fused=applySpecialistEvidence(Object.fromEntries(fields.map(key=>[key,g.result[key]])),evidence);
      fusionDecision=v.technicalComplete?decision(fused.verdict):'technical_error';
    }
    rows.push({id:item.id,sha256:item.sha256,parentId:item.parentId,cohort:item.cohort,generator:item.generator,quality:item.quality,labelEvidenceStrength:item.labelEvidenceStrength,
      gemini:geminiDecision,sightengine:v.decision==='persistent_ai_indicators'?'ai':v.decision==='no_clear_indicators'?'clear':v.decision==='inconclusive'?'inconclusive':'technical_error',
      fusion:fusionDecision,geminiVerdict:g.result?.verdict??null,fusionVerdict:fused?.verdict??null,fusionAssessment:fused,
      geminiPassFailures:g.usage?.failedPasses??null,geminiUsage:g.usage??null,elapsedSeconds:g.elapsedMs/1000,
      specialistIsolatedAlerts:s.temporal?.isolatedAlerts??[],specialistPersistentRuns:s.temporal?.persistentRuns??[],specialistReviewRequired:s.temporal?.reviewRequired??null});
  }
  const byMethod=Object.fromEntries(['gemini','sightengine','fusion'].map(key=>[key,summarize(rows,key)]));
  const elapsed=gemini.results.filter(row=>Number.isFinite(row.elapsedMs)).map(row=>row.elapsedMs/1000);
  const summary={schemaVersion:1,status:'completed_offline_paired_development_comparison',byMethod,referenceAcceptanceChecks:Object.fromEntries(Object.entries(byMethod).map(([key,value])=>[key,referenceGates(value,rows,key)])),
    counts:gemini.counts,usage:gemini.usage,
    completedPassesInvalidForCorroboration:gemini.results.flatMap(row=>row.result?.videoAnalysis?.inspection?.passes??[]).filter(pass=>pass.status==='complete'&&pass.validForCorroboration===false).length,
    latencySeconds:{median:percentile(elapsed,.5),p95Linear:percentile(elapsed,.95),wall:gemini.elapsedMs/1000},
    changeFromGemini:{publisherClearMissesToInconclusive:rows.filter(row=>row.cohort==='publisher_assigned_ai'&&row.gemini==='clear'&&row.fusion==='inconclusive').map(row=>row.id),
      publisherAiToInconclusive:rows.filter(row=>row.cohort==='publisher_assigned_ai'&&row.gemini==='ai'&&row.fusion==='inconclusive').map(row=>row.id),
      documentedNegativesClearToInconclusive:rows.filter(row=>row.cohort==='documented_negative'&&row.gemini==='clear'&&row.fusion==='inconclusive').map(row=>row.id)},
    cases:rows,limitations:[
      'This reuses the frozen25 development cases after the standalone Sightengine failure. The rule is a conservative diagnostic comparison, not independent validation or a rescued pass.',
      'Publisher-assigned benchmark recall and the same-parent receipt-backed Veo check are separate. No aggregate accuracy denominator combines their evidence strengths.',
      'Twelve documented negative files represent six parent sources. Variants are dependent; no population FPR or calibrated confidence estimate is supported.',
      'Changing false clear negatives to Inconclusive reduces false reassurance but does not improve unconditional AI recall. Reduced negative clear coverage is reported.',
      'No verified new mixed-positive, subsecond insert, or actual Instagram round trip is tested by this25-case comparison.',
      'Returned pass token counts may omit internal retry/failed-request billing. Successful top-level results do not imply every model pass succeeded.',
      'Offline fusion uses the saved temporal evidence and newly obtained immutable2.8 Gemini outputs; it does not exercise the integrated product transport or upload route.'
    ]};
  await save('summary.json',summary);
  const lines=['# Paired development comparison','',
    'The original standalone Sightengine screen failed and remains failed. This report applies the reviewed conservative application combiner to the same25 files, retaining abstentions and technical failures.','',
    '| Method | Publisher AI detected /12 | AI clear misses | AI inconclusive | Negative AI alerts /12 | Negative clear | Negative inconclusive | Negative parent alerts /6 | Negative parents clear | Same-parent Veo /1 |',
    '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |'];
  for(const [method,m] of Object.entries(byMethod))lines.push(`| ${method} | ${m.publisherAssignedAi.ai} | ${m.publisherAssignedAi.clear} | ${m.publisherAssignedAi.inconclusive} | ${m.documentedNegative.ai} | ${m.documentedNegative.clear} | ${m.documentedNegative.inconclusive} | ${m.documentedNegative.parents.ai} | ${m.documentedNegative.parents.clear} | ${m.sameParentReceiptedVeo.ai} |`);
  lines.push('','Publisher-assigned detections by quality (original/mild/severe, each denominator4):');
  for(const [method,m] of Object.entries(byMethod))lines.push(`- ${method}: ${['original','mild','severe'].map(q=>m.publisherAssignedAi.byQuality[q].ai+'/4').join(', ')}.`);
  lines.push('',`Gemini top-level results: ${gemini.counts.completed} completed, ${gemini.counts.failed} failed, ${gemini.counts.unattempted} unattempted. Failed model passes: ${gemini.usage.failedPasses}; missing pass usage: ${gemini.usage.missingUsagePasses}.`,
    `Observed input/output tokens: ${gemini.usage.inputTokensObserved}/${gemini.usage.outputTokensObserved}. Median ${summary.latencySeconds.median.toFixed(2)}s, p95 ${summary.latencySeconds.p95Linear.toFixed(2)}s; wall ${summary.latencySeconds.wall.toFixed(2)}s.`,
    '',`Gemini clear misses moved to Inconclusive: ${summary.changeFromGemini.publisherClearMissesToInconclusive.length}. Gemini AI detections moved to Inconclusive: ${summary.changeFromGemini.publisherAiToInconclusive.length}. Documented negatives losing a clear result: ${summary.changeFromGemini.documentedNegativesClearToInconclusive.length}.`,
    '',`Reviewed combiner source SHA256: ${expectedSourceSha}. Exact per-case outcomes, original evidence, unresolved specialist alerts, source-parent results and reference acceptance checks are in summary.json.`, '',...summary.limitations.map(text=>'- '+text),'');
  await writeFile(resolve(ROOT,OUTPUT,'REPORT.md'),lines.join('\n'),{flag:'wx'});
  await save('receipt.json',{schemaVersion:1,status:summary.status,createdAt:new Date().toISOString(),apiCalls:0,
    sources:[...sources,{path:MANIFEST,sha256:MANIFEST_SHA},{path:`${GEMINI}/receipt.json`,sha256:await fileHash(`${GEMINI}/receipt.json`)},{path:`${SIGHT}/receipt.json`,sha256:await fileHash(`${SIGHT}/receipt.json`)},
      {path:`${PRIOR_SUMMARY}/receipt.json`,sha256:await fileHash(`${PRIOR_SUMMARY}/receipt.json`)},{path:relative(ROOT,import.meta.filename),sha256:await fileHash(import.meta.filename)}],
    fusionBundleSha256:hash(build.outputFiles[0].contents),summarySha256:await fileHash(`${OUTPUT}/summary.json`),reportSha256:await fileHash(`${OUTPUT}/REPORT.md`)});
  console.log(JSON.stringify({status:summary.status,byMethod,counts:gemini.counts,usage:gemini.usage,latencySeconds:summary.latencySeconds}));
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
