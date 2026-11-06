import test from 'node:test';import assert from 'node:assert/strict';
import {reviewFieldLabel,reviewSelections} from './review-model.js';
test('human field labels retain line numbers',()=>{assert.equal(reviewFieldLabel('line_items.9.unit_price'),'Line 10 · unit price');assert.equal(reviewFieldLabel('invoice_number'),'invoice number');});
test('manual mappings stay bound to a selected PO, and clearing means no mapping',()=>{
 const options={pos:[{po_code:'PO-A',lines:[]},{po_code:'PO-B',lines:[]}]};const candidate={po_reference:{value:null}};
 const mappings={0:{po:'PO-A',code:'SERVICE'},1:{po:'PO-A',code:''}};
 assert.deepEqual(reviewSelections(options,candidate,'PO-A',mappings).mappings,[{invoice_line:0,po_line_code:'SERVICE'}]);
 assert.deepEqual(reviewSelections(options,candidate,'PO-B',mappings).mappings,[]);
 assert.deepEqual(reviewSelections(options,candidate,'',mappings).mappings,[]);
 assert.equal(reviewSelections(options,{po_reference:{value:' PO-a '}},'',{}).po.po_code,'PO-A');
});
