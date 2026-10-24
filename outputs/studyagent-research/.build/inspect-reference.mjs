import fs from 'node:fs/promises';
import {FileBlob, PresentationFile} from '@oai/artifact-tool';
const p = await PresentationFile.importPptx(await FileBlob.load('/Users/sqz/Desktop/教育出题_20261022_v2.pptx'));
await fs.mkdir('reference',{recursive:true});
await fs.writeFile('reference/inspect.ndjson',(await p.inspect({kind:'slide,shape,textbox,image,layout',maxChars:300000})).ndjson);
for (let i=0;i<p.slides.items.length;i++) {
 const b=await p.export({slide:p.slides.items[i],format:'png',scale:0.65});
 await fs.writeFile(`reference/slide-${i+1}.png`,new Uint8Array(await b.arrayBuffer()));
}
await fs.writeFile('reference/slide-5.layout.json',await (await p.slides.items[4].export({format:'layout'})).text());
console.log('Rendered',p.slides.items.length,'slides');
