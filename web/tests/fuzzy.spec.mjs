import {test,expect} from '@playwright/test';
import {startPanel} from './panel-helper.mjs';

async function open(page){
 const panel=await startPanel();
 await page.goto(panel.url);
 return panel;
}

test('fuzzy subsequence abbreviations rank tighter matches and reject nonmatches',async({page})=>{
 const panel=await open(page);try{
  const result=await page.evaluate(async()=>{
   const f=await import('/static/js/core/fuzzy.js');
   return [f.fuzzyScore('ItemType','IT'),f.fuzzyScore('ItemType','ItemT'),Number.isFinite(f.fuzzyScore('Quest','IT'))];
  });
  expect(result[0]).toBeLessThan(result[1]);
  expect(result[2]).toBe(false);
 }finally{await panel.close();}
});

test('fuzzy ranking breaks ties deterministically by name',async({page})=>{
 const panel=await open(page);try{
  const result=await page.evaluate(async()=>{
   const f=await import('/static/js/core/fuzzy.js');
   const items=[{n:'Item'},{n:'ItemType'},{n:'ItemRarity'}];
   const rank=()=>f.rank(items,'it',x=>x.n).map(x=>x.name);
   return [rank(),rank()];
  });
  expect(result[0][0]).toBe('Item');
  expect(result[0]).toEqual(result[1]);
 }finally{await panel.close();}
});

test('fuzzy highlighting returns matched source ranges and none for nonmatches',async({page})=>{
 const panel=await open(page);try{
  const result=await page.evaluate(async()=>{
   const f=await import('/static/js/core/fuzzy.js');
   return [f.highlightRanges('ItemRarity','IR'),f.highlightRanges('ItemRarity','zz')];
  });
  expect(result).toEqual([[[0,1],[4,5]],[]]);
 }finally{await panel.close();}
});

test('fuzzy highlighting respects astral and length-changing Unicode boundaries',async({page})=>{
 const panel=await open(page);try{
  const result=await page.evaluate(async()=>{
   const f=await import('/static/js/core/fuzzy.js');
   return {
    astralQuery:f.highlightRanges('𝐀R','𝐀'),
    astralText:f.highlightRanges('𝐀R','R'),
    lengthChangingLower:f.highlightRanges('İtemRarity','IR'),
   };
  });
  expect(result).toEqual({astralQuery:[[0,2]],astralText:[[2,3]],lengthChangingLower:[[0,1],[4,5]]});
 }finally{await panel.close();}
});
