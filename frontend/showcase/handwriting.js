/* Keep the student's text exact; only typeset recognizable mathematical runs. */
(function(){
 'use strict';
 const functions=['arcsin','arccos','arctan','sin','cos','tan','cot','sec','csc','log','ln','lim','max','min'];
 const symbols={'π':'\\pi ','α':'\\alpha ','β':'\\beta ','γ':'\\gamma ','θ':'\\theta ','φ':'\\phi ','Δ':'\\Delta ','Σ':'\\sum ','∞':'\\infty ','∈':'\\in ','⊥':'\\perp ','≤':'\\le ','≥':'\\ge ','≠':'\\ne ','±':'\\pm ','·':'\\cdot ','×':'\\times ','÷':'\\div ','−':'-','→':'\\to '};
 const mathCharacter=/[A-Za-z0-9αβγθφπΔΣ∞∈⊥≤≥≠±·×÷−→√²³′'_^=+\-*\/<>()[\]{},.|!% \t]/;
 const punctuation=/[，。、；：！？“”‘’「」『』【】…—]/;
 function syntax(message){throw new Error(message);}
 function typeset(source){
  if(/√(?:\d+(?:\.\d+)?|[A-Za-zαβγθφπ])(?:[²³]|\^)/.test(source))syntax('Ambiguous radical extent');
  let at=0;const fractionsSafe=!/[|!%]/.test(source);
  function argument(){
   while(source[at]===' '||source[at]==='\t')at++;
   const char=source[at];
   if(char==='('||char==='{'){
    const close=char==='('?')':'}';at++;const inner=expression(close);if(source[at]!==close)syntax('Unclosed script');at++;return inner;
   }
   const number=source.slice(at).match(/^\d+(?:\.\d+)?/);if(number){at+=number[0].length;return number[0];}
   if(/[A-Za-z]/.test(char||'')){at++;return char;}
   if(symbols[char]&&!['∈','⊥','≤','≥','≠','±','·','×','÷','→'].includes(char)){at++;return symbols[char];}
   syntax('Ambiguous script or root');
  }
  function joinTerm(tokens){
   const divide=tokens.flatMap((token,index)=>token.type==='slash'?[index]:[]);
   if(fractionsSafe&&divide.length===1){
    const index=divide[0],left=tokens.slice(0,index),right=tokens.slice(index+1);
    // A single denominator atom is unambiguous. Keep a/bc and chained slashes as written.
    if(left.length&&left.every(t=>t.type!=='slash')&&right.length===1&&right[0].type==='atom')return '\\frac{'+left.map(t=>t.tex).join('')+'}{'+right[0].tex+'}';
   }
   return tokens.map(token=>token.tex).join('');
  }
  function expression(close){
   const tokens=[];
   while(at<source.length&&source[at]!==close){
    const char=source[at];
    if(char===' '||char==='\t'){at++;continue;}
    if(char==='('||char==='['||char==='{'){
     const closing={'(':')','[':']','{':'}'}[char];at++;const inner=expression(closing);if(source[at]!==closing)syntax('Unclosed group');at++;
     tokens.push({type:'atom',tex:char==='{'?'\\{'+inner+'\\}':'\\left'+char+inner+'\\right'+closing});continue;
    }
    if(')]}'.includes(char))syntax('Unmatched group');
    if(char==='_'||char==='^'){
     if(!tokens.length||tokens.at(-1).type!=='atom')syntax('Missing script base');at++;tokens.at(-1).tex+=char+'{'+argument()+'}';continue;
    }
    if(char==='²'||char==='³'||char==='′'||char==="'"){
     if(!tokens.length||tokens.at(-1).type!=='atom')syntax('Missing superscript base');at++;tokens.at(-1).tex+=char==='²'?'^{2}':char==='³'?'^{3}':"'";continue;
    }
    if(char==='√'){at++;tokens.push({type:'atom',tex:'\\sqrt{'+argument()+'}'});continue;}
    const number=source.slice(at).match(/^(?:\d+(?:\.\d+)?|\.\d+)/);if(number){at+=number[0].length;tokens.push({type:'atom',tex:number[0]});continue;}
    const fn=functions.find(name=>source.startsWith(name,at));if(fn){at+=fn.length;tokens.push({type:'atom',tex:'\\'+fn+' '});continue;}
    if(/[A-Za-z]/.test(char)){at++;tokens.push({type:'atom',tex:char});continue;}
    if(char==='/'){at++;tokens.push({type:'slash',tex:'/'});continue;}
    if(symbols[char]){at++;tokens.push({type:/[∈⊥≤≥≠±→]/.test(char)?'boundary':'atom',tex:symbols[char]});continue;}
    if('+-=<>;,'.includes(char)){at++;tokens.push({type:'boundary',tex:char});continue;}
    if(char==='*'){at++;tokens.push({type:'atom',tex:'\\cdot '});continue;}
    if(char==='|'||char==='!'){at++;tokens.push({type:'atom',tex:char});continue;}
    if(char==='%'){at++;tokens.push({type:'atom',tex:'\\%'});continue;}
    syntax('Unsupported notation');
   }
   let text='',term=[];for(const token of tokens){if(token.type==='boundary'){text+=joinTerm(term)+token.tex;term=[];}else term.push(token);}return text+joinTerm(term);
  }
  const result=expression(null);if(at!==source.length)syntax('Unconsumed input');return result;
 }
 function plausible(source){
  const value=source.trim();if(!value)return false;
  return /[0-9_=+\-\/<>√²³πΣ∈⊥≤≥≠^]/.test(value)||/^[A-Za-z]{1,3}(?:′|')?$/.test(value)||functions.some(name=>value.startsWith(name));
 }
 function mathRun(ink,source,explicit=false){
  const leading=source.match(/^\s*/)[0],trailing=source.match(/\s*$/)[0];
  const core=source.slice(leading.length,source.length-trailing.length||undefined);
  if(!core||!window.katex||(!explicit&&!plausible(core))){ink.append(document.createTextNode(source));return;}
  const span=document.createElement('span');span.className='paper-math';span.dataset.source=core;
  try{
   const tex=explicit?core:typeset(core);
   katex.render(tex,span,{displayMode:false,throwOnError:true,trust:false,strict:'ignore',output:'htmlAndMathml'});
   if(leading)ink.append(document.createTextNode(leading));ink.append(span);if(trailing)ink.append(document.createTextNode(trailing));
  }catch{ink.append(document.createTextNode(source));}
 }
 function render(text){
  const source=String(text??''),paper=document.createElement('div'),ink=document.createElement('div');
  paper.className='handwriting-sheet';paper.dataset.source=source;ink.className='paper-ink paper-ink-typeset';
  let index=0;
  while(index<source.length){
   // Delimited TeX is validated by KaTeX, never interpreted as HTML.
   const opener=source.startsWith('\\(',index)?'\\(':source.startsWith('\\[',index)?'\\[':source.startsWith('$$',index)?'$$':source[index]==='$'?'$':null;
   if(opener){const closing=opener==='\\('? '\\)':opener==='\\['?'\\]':opener,end=source.indexOf(closing,index+opener.length);if(end>index+opener.length){const raw=source.slice(index+opener.length,end),span=document.createElement('span');span.className='paper-tex-source';span.dataset.source=source.slice(index,end+closing.length);mathRun(span,raw,true);if(span.querySelector('.paper-math'))ink.append(span);else ink.append(document.createTextNode(span.dataset.source));index=end+closing.length;continue;}}
   if(punctuation.test(source[index])){let end=index+1;while(end<source.length&&punctuation.test(source[end]))end++;const span=document.createElement('span');span.className='paper-punctuation';span.dataset.source=source.slice(index,end);span.textContent='\u2060'+span.dataset.source;ink.append(span);index=end;continue;}
   if(mathCharacter.test(source[index])){let end=index+1;while(end<source.length&&mathCharacter.test(source[end]))end++;mathRun(ink,source.slice(index,end));index=end;continue;}
   const start=index++;while(index<source.length&&!mathCharacter.test(source[index])&&!punctuation.test(source[index])&&!source.startsWith('\\(',index)&&!source.startsWith('\\[',index)&&source[index]!=='$')index++;ink.append(document.createTextNode(source.slice(start,index)));
  }
  paper.append(ink);return paper;
 }
 window.ShowcaseHandwriting={render,typeset};
})();
