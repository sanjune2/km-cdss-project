const text = (value) => value == null ? '' : String(value).trim()

export function formatOriginalDose(herb) {
  const amount = text(herb.amount ?? herb.quantity)
  const unit = text(herb.unit)
  const note = text(herb.originalDoseInfo)
  if (amount) return `${amount} ${unit || '(단위 미등록)'}`
  return note ? `원문 메모: ${note}` : '원본 용량 미등록'
}

export function formatPrescribedDose(herb) {
  const amount = text(herb.prescribedAmount)
  const unit = text(herb.prescribedUnit)
  return amount && unit ? `${amount} ${unit}` : '미입력'
}

export function serializeIngredient(herb) {
  const reference = herb.compositionId != null ? {
    compositionId: herb.compositionId, id: herb.id ?? null, name: herb.name,
    amount: herb.amount ?? null, unit: herb.unit ?? null,
    preparation: herb.preparation ?? null, originalDoseInfo: herb.originalDoseInfo ?? null,
  } : {
    compositionId: null, id: herb.id ?? null, name: herb.name.trim(),
    amount: null, unit: null, preparation: null, originalDoseInfo: null,
  }
  return { ...reference,
    prescribedAmount: text(herb.prescribedAmount) || null,
    prescribedUnit: text(herb.prescribedUnit) || null,
  }
}

export function doseInputError(herbs) {
  for (const herb of herbs) {
    const amount = text(herb.prescribedAmount)
    const unit = text(herb.prescribedUnit)
    if (Boolean(amount) !== Boolean(unit)) return '실제 처방량과 단위를 함께 입력해주세요.'
    if (amount && (!/^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$/.test(amount) || amount.length > 32 || Number(amount) <= 0)) {
      return '실제 처방량은 0보다 큰 수치로 입력해주세요.'
    }
    if (unit.length > 32 || [...unit].some((char) => char.charCodeAt(0) < 32)) return '실제 처방량 단위를 확인해주세요.'
  }
  return ''
}

export function prescriptionCandidates(result) {
  const seen = new Set()
  return [...(result?.candidates ?? []), ...(result?.unscoredCandidates ?? [])]
    .filter((candidate) => !seen.has(candidate.id) && seen.add(candidate.id))
}

export function evaluationLabel(candidate) {
  if (candidate.evaluationStatus === 'INSUFFICIENT_DATA') return '미평가 · 설명 자료 부족'
  if (candidate.evaluationStatus === 'POLICY_NOT_CONFIGURED') return '미평가 · 평가 정책 미설정'
  return '평가 완료'
}

export function selectedDiseaseForCatalog(recommendation, navigationState, caseId) {
  if (recommendation) return recommendation.selectedDiseaseId ?? null
  if (String(navigationState?.consultationId) === String(caseId)) return navigationState?.selectedDiseaseId ?? null
  return null
}
