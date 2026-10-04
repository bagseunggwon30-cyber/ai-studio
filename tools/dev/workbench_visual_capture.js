async (page) => {
  await page.setViewportSize({width:1585,height:1080});
  await page.reload(); await page.waitForFunction(()=>Data.loaded);
  if (await page.locator('#workbench-screen').isHidden()) await page.locator('.bd-nav').getByRole('button',{name:'기능 작업대',exact:true}).click();
  await page.locator('.wb-run-history > summary').click();
  await page.locator('.wb-run').first().click();
  await page.waitForFunction(()=>document.querySelector('.wb-run-bar')&&!document.querySelector('.wb-run-bar').hidden&&!document.querySelector('.wb-primary-actions'));
  await page.locator('[data-node="visual-review"]').click();
  await page.waitForFunction(()=>document.querySelector('[data-node="visual-review"]').getAttribute('aria-expanded')==='true');
  if (await page.locator('.wb-run-history').evaluate(e=>e.open)) await page.locator('.wb-run-history > summary').click();
  await page.evaluate(()=>{document.querySelector('#workbench-screen').scrollTop=0;document.querySelector('.wb-graph-scroll').scrollLeft=0;});
  const geometry=await page.locator('.wb-canvas').evaluate(canvas=>({
    headerVisible:document.querySelector('.wb-header').getBoundingClientRect().top>=0,
    folderWidth:canvas.querySelector('.wb-expanded-folder').getBoundingClientRect().width,
    proofWidth:canvas.querySelector('.wb-detail').getBoundingClientRect().width,
    contentFits:[...canvas.querySelectorAll('[data-node]')].every(node=>node.querySelector('.wb-node-state').getBoundingClientRect().bottom<=node.getBoundingClientRect().bottom+1),
    historyClosed:!document.querySelector('.wb-run-history').open,
    advancedClosed:!canvas.querySelector('.wb-advanced').open,
    approvalLocked:canvas.querySelector('.wb-proof-panel .wb-detail-actions button:last-child').disabled,
    verified:canvas.querySelectorAll('.wb-proof-items > .verified').length,
    missing:canvas.querySelectorAll('.wb-proof-items > .missing').length,
  }));
  if (!geometry.headerVisible||!geometry.contentFits||!geometry.historyClosed||!geometry.advancedClosed||!geometry.approvalLocked||geometry.verified!==2||geometry.missing!==1) throw new Error(JSON.stringify(geometry));
  await page.screenshot({path:'output/playwright/workbench-visual-polished.png',fullPage:true,animations:'disabled'});
  return {status:'representative_ready_for_visual_review',geometry,real_model_calls:0,production_writes:0};
}
