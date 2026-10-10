import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
const require = createRequire(import.meta.url);
const math = require('../frontend/pool-math.js');
const katex = require('../frontend/vendor/katex/katex.min.js');
function formulas(text) {
  return math.parts(text).flatMap(part => part.type === 'table' ? part.rows.flatMap(row => row.flatMap(cell => formulas(cell.text))) : part.type === 'math' ? [part] : []);
}
function verify(text) {
  const entries = formulas(text);
  assert.ok(entries.length, text);
  return entries.map(part => katex.renderToString(part.text, {displayMode:part.display, throwOnError:true, trust:false, strict:'ignore', macros:{...math.macros}})).join('');
}
// Regressions found by auditing all 31,049 real candidates, not a second
// implementation of the parser. Every adapted formula must actually parse.
assert.match(verify(String.raw`当 $x=0$ 时，$f(0)=______$。`), /underline/);
assert.match(verify(String.raw`$$\begin{cases}x=1,\$$4pt]y=2.\end{cases}$$`), /mtable/);
verify(String.raw`$f(x)=\begin{cases}\frac12x-1,&$（$x\ge0$）$,\\\frac1x,&$（$x<0$）$.\end{cases}$`);
verify(String.raw`$\dfrac1\mathrm{e}+\frac\e2+\bs0+\myarc{AB}$`);
verify(String.raw`$27\,^{\circ}\mathrm{C}$`);
verify(String.raw`\examdisplaycases{f(x)=}{x-4,&x\ge\lambda,\\x^2-4x+3,&x<\lambda}`);
verify(String.raw`\examdisplaychain{x&=1+2\\&=3}`);
verify(String.raw`\examdisplayarray{}{c|cc}{x&1&2\\\hline f(x)&3&4}{}`);
verify(String.raw`$\begin{cases}x=2+\cos\theta,\\y=1+\sin\theta\end{cases}\text{（$\theta$ 为参数）}$`);
verify(String.raw`\( $h=\sqrt3$ \)`);
verify(String.raw`\begin{align*}x&=1+2\\&=3\end{align*}`);
assert.match(verify(String.raw`由渐近线方程y=\pm\sqrt3x可知\frac ba=\sqrt3。`), /mfrac/);
verify(String.raw`\thereforex_{1}+x_{2}=4,\angleAPB=60^\circ,\sinA=1,\sinh x=2`);
assert.match(formulas(String.raw`$\sinh x+\cosh y$`)[0].text, /\\sinh x\+\\cosh y/);
const joinedCommands = formulas(String.raw`$\Leftrightarrowx+\cosMAD+\sina+\piR$`)[0].text;
assert.equal(joinedCommands, String.raw`\Leftrightarrow x+\cos MAD+\sin a+\pi R`);
verify(String.raw`$\Leftrightarrowx+\cosMAD+\sina+\piR$`);
verify(String.raw`$\Perp+\Square+\oversetfrown{CB}+\textasciitilde$`);
verify(String.raw`$\section*{【详解】}$`);
assert.ok(math.parts(String.raw`\FigureTrimDeclare{img/figure.png}{0bp 0bp 0bp 0bp}`).map(part => part.text || '').join('').includes('[原题含图，本阶段暂缓]'));
verify(String.raw`$\parbox[c][4.2cm][c]{3.0cm}{\frac12}+\resizebox{\linewidth}{!}{x^2}$`);
verify(String.raw`\parbox[c][4.2cm][c]{3.0cm}{\frac12}`);
verify(String.raw`$\smash{\rlap{\raisebox{1cm}{\hspace{-0.3cm}\rotatebox{-19.75}{\rule{4.49cm}{0.4pt}}}}}$`);

const table = math.parts(String.raw`\begin{tabular}{c@{\qquad}c}\begin{tabular}{c|cc}$\oplus$&$a$&$b$\\a&a&b\end{tabular}&\begin{tabular}{cc}值&$\frac12$\end{tabular}\end{tabular}`)[0];
assert.equal(table.type, 'table');
assert.equal(table.rows.length, 1);
assert.equal(table.rows[0].length, 2);
verify(table.rows[0][0].text); verify(table.rows[0][1].text);
const distribution = math.parts(String.raw`$$\begin{tabular}{c|cc}$\xi$&$0$&$1$\\\hline $P(\xi)$&$\frac15$&$\frac45$\end{tabular}$$`)[0];
assert.equal(distribution.type, 'table');
assert.equal(distribution.rows.length, 2);
verify(String.raw`$$\begin{tabular}{c|cc}$\xi$&$0$&$1$\\\hline $P(\xi)$&$\frac15$&$\frac45$\end{tabular}$$`);
const spanning = math.parts(String.raw`\begin{tabular}{ccc}\multicolumn{3}{c}{总计}\\1&2&3\end{tabular}`)[0];
assert.equal(spanning.rows[0][0].span, 3);
assert.equal(spanning.rows[0][0].text, '总计');

// Malformed source stays visible and carries a review note, not guessed math.
assert.ok(math.parts(String.raw`$x=\frac{1}{2$`).some(part => part.warning));
class Element {
  constructor(tag) {this.tag = tag; this.children = []; this.textContent = ''; this.className = '';}
  replaceChildren() {this.children = [];}
  appendChild(child) {this.children.push(child);}
}
const doc = {createElement:tag => new Element(tag)};
const box = new Element('div');
const safeKatex = {render(text,node,options) {node.textContent = katex.renderToString(text, options);}};
const bad = math.render(box, String.raw`<img src=x onerror=alert(1)> $\UnknownSourceMacro{a}$`, {document:doc,katex:safeKatex});
assert.ok(bad.warnings.length);
assert.equal(box.children.some(node => node.tag === 'img'), false);
assert.ok(box.children.some(node => node.textContent.includes('<img')));
assert.ok(box.children.some(node => node.textContent.includes('\UnknownSourceMacro')));
assert.ok(box.children.some(node => node.className === 'pool-math-warning'));
assert.doesNotMatch(verify(String.raw`$\href{javascript:alert(1)}{x}$`), /href=/);
const html = fs.readFileSync(new URL('../frontend/question-pool.html', import.meta.url), 'utf8');
assert.doesNotMatch(html, /cdn\.jsdelivr/);
assert.match(html, /vendor\/katex\/katex\.min\.js/);
const css = fs.readFileSync(new URL('../frontend/vendor/katex/katex.min.css', import.meta.url), 'utf8');
for (const [, font] of css.matchAll(/url\(([^)]+)\)/g)) assert.ok(fs.existsSync(new URL('../frontend/vendor/katex/' + font, import.meta.url)), font);
console.log('Pool formula rendering regressions passed');
