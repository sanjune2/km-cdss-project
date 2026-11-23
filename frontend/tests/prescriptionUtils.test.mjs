import assert from 'node:assert/strict'
import { test } from 'node:test'
import { doseInputError, evaluationLabel, formatOriginalDose, formatPrescribedDose,
  prescriptionCandidates, selectedDiseaseForCatalog, serializeIngredient } from '../src/prescriptionUtils.js'

test('reference display preserves units, zero, notes and explicit missing state', () => {
  assert.equal(formatOriginalDose({ amount: '9.0', unit: 'L' }), '9.0 L')
  assert.equal(formatOriginalDose({ amount: 0, unit: 'mL' }), '0 mL')
  assert.equal(formatOriginalDose({ amount: '2' }), '2 (단위 미등록)')
  assert.equal(formatOriginalDose({ originalDoseInfo: '다른 약재와 같은 분량' }), '원문 메모: 다른 약재와 같은 분량')
  assert.equal(formatOriginalDose({}), '원본 용량 미등록')
  assert.equal(formatOriginalDose({ quantity: '2.5', unit: 'mL' }), '2.5 mL')
  assert.equal(formatPrescribedDose({}), '미입력')
})

test('saving and correcting preserve reference and separately serialize actual dose', () => {
  const source = { compositionId: 3, id: 4, name: '약재', amount: '9', unit: 'L',
    preparation: null, originalDoseInfo: '원본', prescribedAmount: ' 1.25 ', prescribedUnit: ' mL ' }
  const payload = serializeIngredient(source)
  assert.equal(payload.amount, '9')
  assert.equal(payload.unit, 'L')
  assert.equal(payload.prescribedAmount, '1.25')
  assert.equal(payload.prescribedUnit, 'mL')
  const manual = serializeIngredient({ name: ' 직접 약재 ', prescribedAmount: '2', prescribedUnit: 'g' })
  assert.equal(manual.amount, null)
  assert.equal(manual.name, '직접 약재')
  assert.equal(manual.prescribedAmount, '2')
  assert.equal(doseInputError([payload, manual]), '')
})

test('invalid or incomplete actual dose cannot be submitted', () => {
  for (const herb of [{ prescribedAmount: '1' }, { prescribedUnit: 'g' },
    { prescribedAmount: '0', prescribedUnit: 'g' }, { prescribedAmount: 'NaN', prescribedUnit: 'g' },
    { prescribedAmount: '-1', prescribedUnit: 'g' }, { prescribedAmount: '1', prescribedUnit: 'g\nx' }]) {
    assert.ok(doseInputError([herb]))
  }
  assert.equal(doseInputError([{}]), '')
})

test('unscored linked candidates remain selectable without fabricated ranking', () => {
  const unscored = { id: 2, evaluationStatus: 'INSUFFICIENT_DATA', rank: null, score: null }
  assert.deepEqual(prescriptionCandidates({ candidates: [{ id: 1 }], unscoredCandidates: [unscored, { id: 1 }] }), [{ id: 1 }, unscored])
  assert.equal(prescriptionCandidates({ candidates: [], unscoredCandidates: [unscored] }).length, 1)
  assert.equal(evaluationLabel(unscored), '미평가 · 설명 자료 부족')
})

test('catalog disease comes from current saved result, never another consultation', () => {
  assert.equal(selectedDiseaseForCatalog({ selectedDiseaseId: 84 }, {}, '6'), 84)
  assert.equal(selectedDiseaseForCatalog(null, { consultationId: 6, selectedDiseaseId: 84 }, '6'), 84)
  assert.equal(selectedDiseaseForCatalog(null, { consultationId: 5, selectedDiseaseId: 84 }, '6'), null)
})
