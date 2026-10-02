const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('static/index.html', 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const flush = () => new Promise(setImmediate);
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve=yes;reject=no;});
  return {promise,resolve,reject};
}
function response(reply='نص من الخادم', articles=[]) {
  return {ok:true,json:async()=>({reply,retrieved_articles:articles})};
}
function fixture(chatFetch=async()=>response()) {
  const elements = new Map(), calls=[];
  function element() {
    return {value:'',_text:'',innerHTML:'',style:{},children:[],
      get textContent(){return this._text;},
      set textContent(value){this._text=value;this.children=[];},
      appendChild(child){this.children.push(child);},querySelector(){return null;},
      addEventListener(){},parentNode:{removeChild(){}},className:'',disabled:false};
  }
  function get(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}
  const context={AbortController,document:{getElementById:get,createElement:element},
    fetch:(url,options)=>{
      calls.push({url,options});
      if(url.startsWith('/api/articles'))return Promise.resolve({ok:true,json:async()=>
        ({total:1,items:[{id:'fixed',title:'<title>',content:'<script>unsafe</script>',source:'civil'}]})});
      return chatFetch(url,options);
    }};
  vm.createContext(context);vm.runInContext(script,context);
  function send(text){get('access-token').value='private-token';get('msginp').value=text;context.send();}
  return {context,get,calls,send};
}
const tests = [
  ['existing authorization, canonical case, disabled features, and escaping', async()=>{
    const {context,get,calls,send}=fixture();await flush();
    assert(get('dblist').innerHTML.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
    assert(!html.includes('type="file"'));assert(!script.includes('FileReader'));
    assert(!script.includes('localStorage'));assert(html.includes('id="bp" disabled'));
    get('msginp').value='كفالة';context.send();assert(!calls.some(c=>c.url==='/api/chat'));
    send('كفالة');await flush();
    const chat=calls.find(c=>c.url==='/api/chat');assert(chat);
    assert.equal(chat.options.headers.Authorization,'Bearer private-token');
    const payload=JSON.parse(chat.options.body);
    assert.equal(payload.case_type,'financial');assert.equal(payload.messages[0].content,'كفالة');
    context.setCT('personal');assert.equal(context.CT,'financial');
  }],
  ['reset aborts the old request and ignores its late successful response', async()=>{
    const old=deferred(), next=deferred();let count=0;
    const {context,get,calls,send}=fixture(()=>++count===1?old.promise:next.promise);
    send('القضية السابقة');const first=calls.find(c=>c.url==='/api/chat');
    context.reset();assert(first.options.signal.aborted);
    assert.equal(get('sendbtn').disabled,false);
    send('القضية الجديدة');
    old.resolve(response('رد قديم',[{title:'مادة قديمة',content:'قديم',source:'civil'}]));await flush();
    assert.equal(context.msgs.length,1);assert.equal(context.msgs[0].content,'القضية الجديدة');
    assert.equal(get('sendbtn').disabled,true);assert.equal(context.loading,true);
    assert.notEqual(get('ragbox').style.display,'block');
    next.resolve(response('رد جديد'));await flush();
    assert.equal(context.msgs[1].content,'رد جديد');assert.equal(get('sendbtn').disabled,false);
    send('متابعة');
    const roles=JSON.parse(calls.filter(c=>c.url==='/api/chat').at(-1).options.body).messages.map(m=>m.role);
    assert.deepEqual(roles,['user','assistant','user']);
  }],
  ['reset ignores late rejection without removing a new message or unlocking its request', async()=>{
    const old=deferred(), next=deferred();let count=0;
    const {context,get,send}=fixture(()=>++count===1?old.promise:next.promise);
    send('قديم');context.reset();send('جديد');old.reject(new Error('late network failure'));await flush();
    assert.equal(context.msgs.length,1);assert.equal(context.msgs[0].content,'جديد');
    assert.equal(get('errbox').style.display,'none');assert.equal(get('sendbtn').disabled,true);
    next.resolve(response('رد جديد'));await flush();
  }],
  ['reset during JSON parsing also ignores the old result', async()=>{
    const body=deferred();const {context,get,send}=fixture(async()=>({json:()=>body.promise}));
    send('قديم');await flush();context.reset();
    body.resolve({reply:'رد قديم',retrieved_articles:[]});await flush();
    assert.equal(context.msgs.length,0);assert.equal(get('sendbtn').disabled,false);
  }],
  ['a response without retrieved articles clears and hides previous retrieval', async()=>{
    let count=0;const {get,send}=fixture(async()=>++count===1?
      response('رد بمادة',[{title:'مادة سابقة',content:'نص سابق',source:'civil'}]):response('لا توجد مواد',[]));
    send('كفالة');await flush();assert.equal(get('ragbox').style.display,'block');
    assert.equal(get('ragtags').children.length,1);
    send('zzzzzzzz');await flush();
    assert.equal(get('ragbox').style.display,'none');assert.equal(get('ragtags').children.length,0);
    assert.equal(get('ragtags').textContent,'');
  }],
];
(async()=>{
  for(const [name,test] of tests){await test();console.log('PASS: '+name);}
  console.log(`${tests.length} frontend test scenarios passed.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
