import {test,expect} from '@playwright/test';
import {startPanel} from './panel-helper.mjs';

for(const count of [100,1000,10000]){
 test(`resource list ${count} entries stays virtualized and paints within budget`,async({page})=>{
  const panel=await startPanel();
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  try{
   const digits=Math.max(4,String(count-1).length);
   const resources=Array.from({length:count},(_,index)=>{
    const name=`Table${String(index).padStart(digits,'0')}`;
    return {kind:'table',name,resourceId:`table:${name}`,primary:'Id',fields:[{name:'Id',type:'int32'}]};
   });
   await page.route('**/api/schema-workspace',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,data:{revision:'benchmark',schemaRevision:'benchmark',resources,reverseRefs:{}}})}));
   await page.goto(panel.url);
   const started=await page.evaluate(()=>performance.now());
   await page.locator('.ct-sitem[data-module="schema"]').click();
   await expect(page.locator('#page-schema .ct-vlist-window').first()).toBeAttached();
   await page.locator('#resource-toggle').click();
   await expect.poll(()=>page.locator('#page-schema .ct-resource-row').count()).toBeGreaterThan(0);
   const elapsed=await page.evaluate(start=>performance.now()-start,started);
   const visible=await page.locator('#page-schema .ct-resource-row').count();
   const nodes=await page.evaluate(()=>document.querySelectorAll('*').length);
   expect(errors).toEqual([]);
   expect(visible).toBeLessThan(100);
   expect(nodes).toBeLessThan(8000);
   expect(elapsed,`${count} entries first paint`).toBeLessThan(5000);
   const target=`Table${String(count-1).padStart(digits,'0')}`;
   const queryStart=await page.evaluate(()=>performance.now());
   await page.locator('#resource-filter').fill(target);
   await expect(page.locator(`#resource-list .ct-resource-row[data-name="${target}"]`)).toBeVisible();
   const queryMs=await page.evaluate(start=>performance.now()-start,queryStart);
   expect(queryMs,`${count} entries filtered search`).toBeLessThan(2000);
   await page.locator('#resource-filter').fill('');
   await page.locator('#resource-list').evaluate(element=>{
    element.scrollTop=element.scrollHeight;
    element.dispatchEvent(new Event('scroll'));
   });
   await expect(page.locator(`#resource-list .ct-resource-row[data-name="${target}"]`)).toHaveCount(1);
   await page.keyboard.press('Control+p');
   await page.locator('.ct-dialog-mask.open [data-qo-input]').fill(target);
   await expect(page.locator(`.ct-dialog-mask.open [data-qo="${target}"]`)).toBeVisible();
   expect(await page.locator('.ct-dialog-mask.open [data-qo-list] .ct-resource-row').count()).toBeLessThan(100);
   const heap=await page.evaluate(()=>performance.memory?.usedJSHeapSize??null);
   console.log(JSON.stringify({resources:count,firstPaintMs:Math.round(elapsed),queryMs:Math.round(queryMs),domNodes:nodes,visibleRows:visible,heapBytes:heap}));
  }finally{await panel.close();}
 });
}
