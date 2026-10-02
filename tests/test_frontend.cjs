const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('static/index.html', 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const elements = new Map();
function element() {
  return {value:'',textContent:'',innerHTML:'',style:{},appendChild(){},
    querySelector(){return null;},addEventListener(){},parentNode:{removeChild(){}},className:'',disabled:false};
}
function get(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}
const calls=[];
const context={document:{getElementById:get,createElement:element},fetch:async(url,options)=>{
  calls.push({url,options});
  return {ok:true,json:async()=>url.startsWith('/api/articles')?
    {total:1,items:[{id:'fixed',title:'<title>',content:'<script>unsafe</script>',source:'civil'}]}:
    {reply:'نص من الخادم',retrieved_articles:[]}};
}};
vm.createContext(context);
vm.runInContext(script,context);
(async()=>{
  await new Promise(setImmediate);
  assert(get('dblist').innerHTML.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
  assert(!html.includes('type="file"'));
  assert(!script.includes('FileReader'));
  assert(!script.includes('localStorage'));
  assert(html.includes('id="bp" disabled'));
  get('msginp').value='كفالة';
  context.send();
  assert(!calls.some(c=>c.url==='/api/chat'));
  get('access-token').value='private-token';
  context.send();
  await new Promise(setImmediate);
  const chat=calls.find(c=>c.url==='/api/chat');
  assert(chat);
  assert.equal(chat.options.headers.Authorization,'Bearer private-token');
  const payload=JSON.parse(chat.options.body);
  assert.equal(payload.case_type,'financial');
  assert.equal(payload.messages[0].content,'كفالة');
  context.setCT('personal');
  assert.equal(context.CT,'financial');
  console.log('Frontend checks passed: canonical case, authorization, uploads disabled, personal disabled, escaped database text.');
})().catch(error=>{console.error(error);process.exitCode=1;});
