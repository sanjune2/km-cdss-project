
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import IngredientDoseFields from '../components/IngredientDoseFields'
import { doseInputError, evaluationLabel, formatOriginalDose, formatPrescribedDose,
  prescriptionCandidates, selectedDiseaseForCatalog, serializeIngredient } from '../prescriptionUtils'

export default function Prescriptions({ currentRole }) {
  const isDesk = currentRole === 'desk'
  const [printCount, setPrintCount] = useState(0)
  const [printHistoryLoading, setPrintHistoryLoading] = useState(false)
  const [isPrinting, setIsPrinting] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  const patient = location.state?.patient
  const consultationId = location.state?.consultationId
  const isNewPrescription = location.pathname === '/prescription/new'
  const aiPrescription = isNewPrescription ? location.state?.aiPrescription : null
  const navigationResult = location.state?.prescriptionResult
  const [selectedAiPrescription, setSelectedAiPrescription] = useState(() => aiPrescription ? {
    id: aiPrescription.id,
    searchId: navigationResult?.searchId || location.state.prescriptionSearchId,
  } : null)
  const [savedRecommendation, setSavedRecommendation] = useState(null)
  const [showAllRecommendations, setShowAllRecommendations] = useState(false)

  const [selectedPrescription, setSelectedPrescription] = useState(aiPrescription?.name ?? null)
  const [prescriptionSource, setPrescriptionSource] = useState(aiPrescription ? 'ai' : 'manual')
  const [catalogPrescriptionId, setCatalogPrescriptionId] = useState(null)
  const [prescriptionText, setPrescriptionText] = useState('')
  const [consultationRecords, setConsultationRecords] = useState([])
  const [patientRecords, setPatientRecords] = useState([])
  const [selectedConsultationId, setSelectedConsultationId] = useState('')
  const activeConsultationId = consultationId || selectedConsultationId
  const passedRecommendation = navigationResult && String(navigationResult.caseId) === String(activeConsultationId)
    ? navigationResult : null
  const currentRecommendation = savedRecommendation?.caseId === activeConsultationId ? savedRecommendation : null
  const recommendation = passedRecommendation || currentRecommendation?.result
  const recommendedCandidates = prescriptionCandidates(recommendation)
  const [consultationLoadError, setConsultationLoadError] = useState('')
  const [customPrescription, setCustomPrescription] = useState('')
  const [showDirectInput, setShowDirectInput] = useState(false)
  const [showPrescriptionSearch, setShowPrescriptionSearch] = useState(false)
  const [prescriptionSearchQuery, setPrescriptionSearchQuery] = useState('')
  const [catalogResults, setCatalogResults] = useState([])
  const [catalogType, setCatalogType] = useState('prescription')
  const [catalogDetail, setCatalogDetail] = useState(null)
  const [catalogOriginal, setCatalogOriginal] = useState(null)
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [catalogError, setCatalogError] = useState('')
  const [herbs, setHerbs] = useState(aiPrescription?.ingredients ?? [
  { name: '', amount: '' },
 ])

  const addHerb = () => {
    setHerbs((prev) => [...prev, { name: '', amount: '' }])
  }

  const updateHerb = (index, field, value) => {
    setHerbs((prev) =>
      prev.map((herb, i) =>
        i === index ? { ...herb, [field]: value } : herb
      )
    )
  }

  const removeHerb = (index) => {
    setHerbs((prev) => prev.filter((_, i) => i !== index))
  }

  const [isSaving, setIsSaving] = useState(false)
  const [prescriptionRecords, setPrescriptionRecords] = useState([])
  const [detailPrescription, setDetailPrescription] = useState(null)
  const printRxId = detailPrescription?.rxId
  const printVersionId = detailPrescription?.versionId
  const [editPrescription, setEditPrescription] = useState(null)
  const [listError, setListError] = useState('')

  useEffect(() => {
      if (!isDesk || !printRxId || !printVersionId) {
        setPrintCount(0)
        setPrintHistoryLoading(false)
        return
      }

      let cancelled = false

      const fetchPrintHistory = async () => {
        setPrintHistoryLoading(true)
        setPrintCount(0)

        try {
          const response = await fetch(
            `/api/prescriptions/${printRxId}/print-history?versionId=${printVersionId}`,
            {
              credentials: 'include',
            }
          )

          if (!response.ok) {
            throw new Error('인쇄 이력을 불러오지 못했습니다.')
          }

          const data = await response.json()

          if (!cancelled) {
            setPrintCount(data.printCount)
          }
        } catch (error) {
          if (!cancelled) {
            console.error(error)
          }
        } finally {
          if (!cancelled) {
            setPrintHistoryLoading(false)
          }
        }
      }

      fetchPrintHistory()

      return () => {
        cancelled = true
      }
    }, [isDesk, printRxId, printVersionId])

  useEffect(() => {
    if (isNewPrescription) return

    const loadPrescriptions = async () => {
      try {
        setListError('')

        const response = await fetch(
    isDesk ? '/api/prescription-deliveries' : '/api/prescriptions',
      {
            credentials: 'include',
          }
        )

        if (!response.ok) {
          throw new Error('처방전 목록 조회에 실패했습니다.')
        }

        const data = await response.json()
        setPrescriptionRecords((data.records || []).map((record) => ({
          ...record,
          status: isDesk || record.lastDeliveredVersionId === record.currentVersionId ? '전송' : '미전송',
        })))
      } catch (error) {
        console.error('처방전 목록 조회 오류:', error)
        setListError('처방전 목록을 불러오지 못했습니다.')
      }
    }

  loadPrescriptions()
}, [isDesk, isNewPrescription])

    useEffect(() => {
  if (!isNewPrescription) return

  const loadConsultationData = async () => {
    try {
      setConsultationLoadError('')

      const [consultationResponse, patientResponse] = await Promise.all([
        fetch('/api/consultations', {
          credentials: 'include',
        }),
        fetch('/api/patients', {
          credentials: 'include',
        }),
      ])

      if (!consultationResponse.ok || !patientResponse.ok) {
        throw new Error('상담일지 또는 환자 목록 조회 실패')
      }

      const consultationData = await consultationResponse.json()
      const patientData = await patientResponse.json()

      setConsultationRecords(consultationData.records || [])
      setPatientRecords(patientData.patients || [])
    } catch (error) {
      console.error('상담일지 및 환자 조회 오류:', error)
      setConsultationLoadError(
        '상담일지와 환자 정보를 불러오지 못했습니다.'
      )
    }
  }

  loadConsultationData()
}, [isNewPrescription])

  const [savedPrescription, setSavedPrescription] = useState(false)

  useEffect(() => {
    if (!isNewPrescription || !activeConsultationId || passedRecommendation) return
    const controller = new AbortController()
    const read = async (path) => {
      const response = await fetch(path, { credentials: 'include', signal: controller.signal })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error?.message || '저장된 처방 후보를 불러오지 못했습니다.')
      return data
    }
    const path = `/api/consultations/${encodeURIComponent(activeConsultationId)}`
    const loadRecommendation = async () => {
      try {
        const { record } = await read(path)
        const diagnosis = record.diagnosis
        let result = null
        if (diagnosis?.diseaseSearchId && diagnosis.selectedDiseaseId != null) {
          const { records } = await read(`${path}/searches`)
          const linked = records.findLast((item) => item.kind === 'PRESCRIPTION' && item.status === 'COMPLETED'
            && item.diseaseSearchId === String(diagnosis.diseaseSearchId)
            && item.selectedDiseaseId === diagnosis.selectedDiseaseId)
          if (linked) result = await read(`/api/ai/searches/${encodeURIComponent(linked.searchId)}`)
        }
        if (!controller.signal.aborted) setSavedRecommendation({ caseId: activeConsultationId, result })
      } catch (error) {
        if (!controller.signal.aborted) setSavedRecommendation({ caseId: activeConsultationId, error: error.message })
      }
    }
    loadRecommendation()
    return () => controller.abort()
  }, [isNewPrescription, activeConsultationId, passedRecommendation])

  const chooseRecommendedPrescription = (candidate) => {
    setSelectedAiPrescription({ id: candidate.id, searchId: recommendation.searchId })
    setSelectedPrescription(candidate.name)
    setPrescriptionSource('ai')
    setCatalogPrescriptionId(null)
    setPrescriptionText('')
    setHerbs(candidate.ingredients ?? [])
  }

  const savePrescription = async () => {
    if (isSaving || savedPrescription) return
      const selectedConsultation = consultationRecords.find(
          (record) => String(record.id) === selectedConsultationId
        )

        const prescriptionPatient = patient || patientRecords.find(
          (record) =>
            String(record.id) === String(selectedConsultation?.patientId)
        )

        const prescriptionConsultationId =
          consultationId || selectedConsultationId

    if (!prescriptionPatient?.id || !prescriptionConsultationId) {
      alert('환자 또는 상담일지 정보가 없습니다.')
      return
    }

    if (!selectedPrescription?.trim()) {
      alert('처방을 먼저 선택해 주세요.')
      return
    }

    // v1.3: 직접 입력 약재의 원본 용량·단위는 임의로 생성하지 않는다.
    if (herbs.some((herb) => !herb.name.trim())) {
      alert('약재명을 입력해 주세요.')
      return
    }

    const doseError = doseInputError(herbs)
    if (doseError) { alert(doseError); return }

    if (prescriptionSource === 'ai' && !selectedAiPrescription?.searchId) {
      alert('선택한 처방의 검색 기록을 확인할 수 없습니다. 후보 목록에서 다시 선택해 주세요.')
      return
    }
    setIsSaving(true)

    try {
      const response = await fetch(
          '/api/prescriptions',
          {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
            },
          body: JSON.stringify({
            caseId: Number(prescriptionConsultationId),
            diagnosisText: null,
            prescriptionId: prescriptionSource === 'ai' ? selectedAiPrescription.id :
              prescriptionSource === 'catalog' ? catalogPrescriptionId : null,
            prescriptionSearchId: prescriptionSource === 'ai' ? selectedAiPrescription.searchId : null,
            prescriptionName: selectedPrescription.trim(),
            prescriptionText: prescriptionText.trim() || null,
            ingredients: herbs.map(serializeIngredient),
          }),
        }
      )

      const data = await response.json()

      if (!response.ok) {
        alert(data.error?.message || '처방전 저장에 실패했습니다.')
        return
      }

      setSavedPrescription(true)
      alert('처방전이 저장되었습니다.')
    } catch (error) {
      console.error('처방전 저장 오류:', error)
      alert('서버 연결에 실패했습니다.')
    } finally {
      setIsSaving(false)
    }
  }

const [isUpdating, setIsUpdating] = useState(false)

const fetchPrescriptionVersion = async (record) => {
  const path = isDesk
    ? `/api/prescription-deliveries/${record.id}`
    : `/api/prescriptions/${record.id}/versions/${record.currentVersionId}`
  const response = await fetch(path, { credentials: 'include' })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error?.message || '저장본을 불러오지 못했습니다.')
  const version = isDesk ? data.record.version : data.record
  return { ...record, ...version, id: record.id, herbs: version.ingredients }
}

const openPrescriptionDetail = async (record) => {
  try {
    setDetailPrescription(await fetchPrescriptionVersion(record))
  } catch (error) {
    alert(error.message)
  }
}

const openPrescriptionCorrection = async (record) => {
  try {
    setEditPrescription({ ...await fetchPrescriptionVersion(record), reason: '' })
  } catch (error) {
    alert(error.message)
  }
}

const updatePrescription = async () => {
  if (!editPrescription || isUpdating) return

  if (!editPrescription.prescriptionName.trim()) {
    alert('처방명을 입력해 주세요.')
    return
  }

  if (
    editPrescription.herbs.some((herb) => !herb.name.trim()) ||
    !editPrescription.reason.trim()
  ) {
    alert('약재명과 정정 사유를 입력해 주세요.')
    return
  }

  const doseError = doseInputError(editPrescription.herbs)
  if (doseError) { alert(doseError); return }

  setIsUpdating(true)

  try {
    const response = await fetch(
      `/api/prescriptions/${editPrescription.id}`,
      {
        method: 'PATCH',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          caseId: editPrescription.caseId,
          versionId: editPrescription.versionId,
          reason: editPrescription.reason.trim(),
          diagnosisText: editPrescription.diagnosisText,
          prescriptionId: editPrescription.prescriptionId,
          prescriptionSearchId: editPrescription.prescriptionSearchId,
          prescriptionText: editPrescription.prescriptionText,
          prescriptionName: editPrescription.prescriptionName.trim(),
          ingredients: editPrescription.herbs.map(serializeIngredient),
        }),
      }
    )

    const data = await response.json()

    if (!response.ok) {
      alert(
        data.error?.message || '처방전 수정에 실패했습니다.'
      )
      return
    }

    setPrescriptionRecords((prev) =>
      prev.map((record) =>
        record.id === data.record.rxId ? {
          ...record, prescriptionName: data.record.prescriptionName, updatedAt: data.record.savedAt,
          currentVersionId: data.record.versionId, currentVersionNo: data.record.versionNo, status: '미전송',
        } : record
      )
    )

    setDetailPrescription((prev) =>
      prev?.id === data.record.rxId ? { ...prev, ...data.record, herbs: data.record.ingredients } : prev
    )

    setEditPrescription(null)
    alert('처방전이 수정되었습니다.')
  } catch (error) {
    console.error('처방전 수정 오류:', error)
    alert('서버 연결에 실패했습니다.')
  } finally {
    setIsUpdating(false)
  }
}

const sendPrescription = async (record) => {
  if (record.status !== '미전송') return

  const confirmed = window.confirm(
    `${record.patientName} 환자의 처방전을 안내데스크로 전송하시겠습니까?`
  )

  if (!confirmed) return

  try {
    const response = await fetch(
  `/api/prescriptions/${record.id}/send`,
  {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ versionId: record.currentVersionId }),
  }
)

    const data = await response.json()

    if (!response.ok) {
      alert(
        typeof data.detail === 'string'
          ? data.detail
          : '처방전 전송에 실패했습니다.'
      )
      return
    }

    setPrescriptionRecords((prev) =>
      prev.map((item) =>
        item.id === data.record.rxId
          ? { ...item, status: '전송', lastDeliveredVersionId: data.record.versionId }
          : item
      )
    )

    alert('처방전이 안내데스크로 전송되었습니다.')
  } catch (error) {
    console.error('처방전 전송 오류:', error)
    alert('서버 연결에 실패했습니다.')
  }
}

    if (!isNewPrescription) {
      return (
        <div>
          <h2>처방 관리</h2>

          {currentRole !== 'desk' && (
            <button
              type="button"
              onClick={() => navigate('/prescription/new')}
              style={{
                padding: '10px 16px',
                marginBottom: '20px',
                backgroundColor: '#245c46',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
              }}
            >
              AI 신규 처방전 작성 및 저장
            </button>
          )}

          <h3>처방전 이력</h3>

          {listError && <p style={{ color: 'red' }}>{listError}</p>}

          <table
              style={{
                width: '100%',
                maxWidth: '1000px',
                marginTop: '20px',
                borderCollapse: 'collapse',
                tableLayout: 'fixed',
                textAlign: 'center',
              }}
            >
            <thead>
              <tr>
                <th>작성 날짜</th>
                <th>환자명</th>
                <th>처방명</th>
                <th>상태</th>
                <th>작업</th>
              </tr>
            </thead>

            <tbody>
              {prescriptionRecords.map((record) => (
                <tr key={record.id}>
                  <td>{(record.sentAt ?? record.createdAt)?.slice(0, 10)}</td>
                  <td>{record.patientName}</td>
                  <td>{record.prescriptionName}</td>
                  <td>{record.status}</td>
                  <td>
                      <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            whiteSpace: 'nowrap',
                          }}
                        >
                    <button
                      type="button"
                      onClick={() => openPrescriptionDetail(record)}
                    >
                      보기
                    </button>
                      {currentRole !== 'desk' && (
                          <button
                            type="button"
                            onClick={() => openPrescriptionCorrection(record)}
                            style={{ marginLeft: '8px' }}
                          >
                            수정
                          </button>
                        )}
                      {currentRole !== 'desk' && record.status === '미전송' && (
                          <button
                            type="button"
                            onClick={() => sendPrescription(record)}
                            style={{ marginLeft: '8px' }}
                          >
                            전송
                          </button>
                        )}
                      </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {prescriptionRecords.length === 0 && !listError && (
            <p>저장된 처방전이 없습니다.</p>
          )}
            {detailPrescription && (
              <div
                style={{
                  position: 'fixed',
                  inset: 0,
                  backgroundColor: 'rgba(0, 0, 0, 0.5)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  zIndex: 1000,
                }}
              >
                <div
                  role="dialog"
                  aria-modal="true"
                  aria-label="처방전 상세보기"
                  style={{
                    backgroundColor: 'white',
                    padding: '24px',
                    borderRadius: '10px',
                    width: '500px',
                    maxWidth: '90%',
                    maxHeight: '85vh',
                    overflowY: 'auto',
                  }}
                >
                  <h3>처방전 상세보기</h3>

                  <p>환자명: {detailPrescription.patientName}</p>
                  <p>처방명: {detailPrescription.prescriptionName}</p>
                  <p>
                    작성 날짜: {(detailPrescription.savedAt ?? detailPrescription.createdAt)?.slice(0, 10)}
                  </p>
                  <p>상태: {detailPrescription.status}</p>

                  <h4>약재 구성</h4>

                  <table
                    style={{
                      width: '100%',
                      borderCollapse: 'collapse',
                      textAlign: 'center',
                    }}
                  >
                    <thead>
                      <tr>
                        <th>약재명</th>
                        <th>원본 참고량</th>
                        <th>실제 처방량</th>
                      </tr>
                    </thead>

                    <tbody>
                      {detailPrescription.herbs.map((herb, index) => (
                        <tr key={index}>
                          <td style={{ padding: '8px' }}>{herb.name}</td>
                          <td style={{ padding: '8px' }}>
                            {formatOriginalDose(herb)}
                            {herb.amount != null && herb.originalDoseInfo && <p>원문 메모: {herb.originalDoseInfo}</p>}
                          </td>
                          <td style={{ padding: '8px' }}>{formatPrescribedDose(herb)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  <div
                      className="prescription-modal-actions"
                      style={{ marginTop: '20px' }}
                    >
                      {isDesk && (
                        <button
                          type="button"
                          disabled={printHistoryLoading || isPrinting}
                          onClick={async () => {
                            if (printHistoryLoading || isPrinting) return
                            setIsPrinting(true)
                            try {
                              const response = await fetch(
                                `/api/prescriptions/${detailPrescription.rxId}/print?versionId=${detailPrescription.versionId}`,
                                {
                                  method: 'POST',
                                  credentials: 'include',
                                }
                              )

                              if (!response.ok) {
                                const error = await response.json()
                                throw new Error(
                                  error.error?.message || '인쇄 요청 기록에 실패했습니다.'
                                )
                              }

                              setPrintCount((count) => count + 1)
                              window.print()
                            } catch (error) {
                              alert(error.message)
                            } finally {
                              setIsPrinting(false)
                            }
                          }}
                          style={{ marginRight: '10px' }}
                        >
                          {printHistoryLoading
                            ? '인쇄 이력 확인 중...'
                            : printCount > 0
                              ? '재인쇄'
                              : '인쇄'}
                        </button>
                      )}

                      <button
                        type="button"
                        disabled={printHistoryLoading || isPrinting}
                        onClick={() => setDetailPrescription(null)}
                      >
                        닫기
                      </button>
                    </div>
                </div>
              </div>
            )}
            {editPrescription && (
              <div
                style={{
                  position: 'fixed',
                  inset: 0,
                  backgroundColor: 'rgba(0, 0, 0, 0.5)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  zIndex: 1000,
                }}
              >
                <div
                  role="dialog"
                  aria-modal="true"
                  aria-label="처방전 수정"
                  style={{
                    backgroundColor: 'white',
                    padding: '24px',
                    borderRadius: '10px',
                    width: '500px',
                    maxWidth: '90%',
                    maxHeight: '85vh',
                    overflowY: 'auto',
                  }}
                >
                  <h3>처방전 수정</h3>

                  <p>환자명: {editPrescription.patientName}</p>

                  <label>
                    처방명
                    <input
                      type="text"
                      value={editPrescription.prescriptionName}
                      onChange={(e) =>
                        setEditPrescription((prev) => ({
                          ...prev,
                          prescriptionName: e.target.value,
                        }))
                      }
                      style={{
                        display: 'block',
                        width: '100%',
                        boxSizing: 'border-box',
                        padding: '10px',
                        marginTop: '8px',
                      }}
                    />
                  </label>
                  <label>
                    정정 사유
                    <input type="text" value={editPrescription.reason}
                      onChange={(e) => setEditPrescription((prev) => ({ ...prev, reason: e.target.value }))} />
                  </label>

                  <h4>약재 구성</h4>

                  {editPrescription.herbs.map((herb, index) => (
                    <div
                      key={index}
                      style={{
                        display: 'flex',
                        gap: '8px',
                        marginBottom: '10px',
                      }}
                    >
                      <input
                        type="text"
                        placeholder="약재명"
                        value={herb.name}
                        readOnly={herb.id != null || herb.compositionId != null}
                        onChange={(e) =>
                          setEditPrescription((prev) => ({
                            ...prev,
                            herbs: prev.herbs.map((item, i) =>
                              i === index
                                ? { ...item, name: e.target.value }
                                : item
                            ),
                          }))
                        }
                        style={{ flex: 2, minWidth: 0, padding: '10px' }}
                      />

                      <IngredientDoseFields herb={herb} onChange={(field, value) =>
                        setEditPrescription((previous) => ({ ...previous,
                          herbs: previous.herbs.map((item, i) => i === index ? { ...item, [field]: value } : item),
                        }))} />

                      <button
                        type="button"
                        onClick={() =>
                          setEditPrescription((prev) => ({
                            ...prev,
                            herbs: prev.herbs.filter((_, i) => i !== index),
                          }))
                        }
                      >
                        삭제
                      </button>
                    </div>
                  ))}

                  <button
                    type="button"
                    onClick={() =>
                      setEditPrescription((prev) => ({
                        ...prev,
                        herbs: [...prev.herbs, { name: '', amount: '' }],
                      }))
                    }
                  >
                    + 약재 추가
                  </button>

                  <div style={{ marginTop: '24px', display: 'flex', gap: '10px' }}>
                    <button
                      type="button"
                      onClick={updatePrescription}
                      disabled={isUpdating}
                    >
                      {isUpdating ? '수정 중...' : '수정 저장'}
                    </button>

                    <button
                      type="button"
                      onClick={() => setEditPrescription(null)}
                    >
                      취소
                    </button>
                  </div>
                </div>
              </div>
            )}
        </div>
      )
    }
    const searchCatalog = async () => {
      const keyword = prescriptionSearchQuery.trim()

      setCatalogResults([])
      setCatalogDetail(null)
      setCatalogOriginal(null)
      setCatalogError('')

      if (!keyword) {
        setCatalogError('검색어를 입력해 주세요.')
        return
      }

      setCatalogLoading(true)

      try {
        const response = await fetch(
          `/api/catalog/search?type=${catalogType}&query=${encodeURIComponent(keyword)}`,
          { credentials: 'include' }
        )

        const data = await response.json()
        if (!response.ok) throw new Error(data.error?.message || '기업 자료 검색에 실패했습니다.')
        setCatalogResults(data.items)
        if (!data.total) setCatalogError('검색 결과가 없습니다.')
      } catch (error) {
        setCatalogError(error.message)
      } finally {
        setCatalogLoading(false)
      }
    }

    const loadCatalogDetail = async (itemId) => {
      setCatalogLoading(true)
      setCatalogError('')
      setCatalogOriginal(null)

      try {
        const diseaseId = selectedDiseaseForCatalog(recommendation, location.state, activeConsultationId)
        const query = catalogType === 'prescription' && diseaseId != null
          ? `?selectedDiseaseId=${encodeURIComponent(diseaseId)}` : ''
        const response = await fetch(
          `/api/catalog/${catalogType}/${itemId}${query}`,
          { credentials: 'include' }
        )

        const data = await response.json()
        if (!response.ok) throw new Error(data.error?.message || '기업 자료 상세 조회에 실패했습니다.')
        setCatalogDetail(data.record)
      } catch (error) {
        setCatalogError(error.message)
      } finally {
        setCatalogLoading(false)
      }
    }

    const loadCatalogOriginal = async (sourceUrl) => {
      setCatalogLoading(true)
      setCatalogError('')
      try {
        const response = await fetch(sourceUrl, { credentials: 'include' })
        const data = await response.json()
        if (!response.ok) throw new Error(data.error?.message || '원문 조회에 실패했습니다.')
        setCatalogOriginal(data.record)
      } catch (error) {
        setCatalogError(error.message)
      } finally {
        setCatalogLoading(false)
      }
    }

const applyCatalogPrescription = () => {
  if (!catalogDetail) {
    alert('선택할 처방 정보가 없습니다.')
    return
  }


  setSelectedPrescription(catalogDetail.name)
  setPrescriptionSource('catalog')
  setCatalogPrescriptionId(catalogDetail.id)
  setPrescriptionText('')
  setHerbs(catalogDetail.ingredients)


  setSavedPrescription(false)
  setShowDirectInput(false)
  setShowPrescriptionSearch(false)
  setCatalogDetail(null)
  setCatalogResults([])
  setCatalogError('')
}

  return (
    <div>
      <h2>AI 신규 처방전 작성 및 저장</h2>

      <h3>환자 정보</h3>
      {(() => {
          const selectedConsultation = consultationRecords.find(
            (record) => String(record.id) === selectedConsultationId
          )

          const selectedPatient = patient || patientRecords.find(
            (record) =>
              String(record.id) === String(selectedConsultation?.patientId)
          )

          return (
            <div>
              {!patient && (
                <div style={{ marginBottom: '20px' }}>
                  <h3>상담일지 선택</h3>

                  {consultationLoadError && (
                    <p style={{ color: 'red' }}>{consultationLoadError}</p>
                  )}

                  <select
                    value={selectedConsultationId}
                    onChange={(e) => {
                      const nextConsultationId = e.target.value

                      if (nextConsultationId !== selectedConsultationId) {
                        setSelectedConsultationId(nextConsultationId)
                        setSavedRecommendation(null)
                        setShowAllRecommendations(false)
                        setSelectedAiPrescription(null)
                        setSelectedPrescription(null)
                        setPrescriptionSource('manual')
                        setCatalogPrescriptionId(null)
                        setPrescriptionText('')
                        setHerbs([{ name: '', amount: '' }])
                        setCustomPrescription('')
                        setShowDirectInput(false)
                        setShowPrescriptionSearch(false)
                        setCatalogDetail(null)
                        setCatalogOriginal(null)
                        setCatalogResults([])
                        setCatalogError('')
                        setSavedPrescription(false)
                      }
                    }}

                    style={{
                      padding: '10px',
                      width: '100%',
                      maxWidth: '500px',
                    }}
                  >
                    <option value="">상담일지를 선택해주세요.</option>

                    {consultationRecords.map((record) => (
                      <option key={record.id} value={String(record.id)}>
                        {record.patientName} - {record.createdAt?.slice(0, 10)}
                        {' / '}{record.symptoms}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {selectedPatient ? (
                <div>
                  <p>성명: {selectedPatient.name}</p>
                  <p>생년월일: {selectedPatient.birthDate}</p>
                  <p>연락처: {selectedPatient.phone}</p>
                </div>
              ) : (
                <p>연결된 환자 정보가 없습니다.</p>
              )}
            </div>
          )
        })()}

      <h3>AI 추천 처방 목록</h3>
      <div
        style={{
          border: '1px solid #ddd',
          borderRadius: '8px',
          padding: '16px',
          maxWidth: '700px',
        }}
      >
        {recommendedCandidates.length ? (
          <>
            <ol>
              {(showAllRecommendations ? recommendedCandidates : recommendedCandidates.slice(0, 3)).map((candidate) => (
                <li key={candidate.id}>
                  {candidate.name}{' '}
                  <span>{evaluationLabel(candidate)}</span>{' '}
                  <button
                    type="button"
                    disabled={isSaving || savedPrescription ||
                      (prescriptionSource === 'ai' && selectedAiPrescription?.id === candidate.id)}
                    onClick={() => chooseRecommendedPrescription(candidate)}
                  >
                    {prescriptionSource === 'ai' && selectedAiPrescription?.id === candidate.id ? '선택됨' : '선택'}
                  </button>
                </li>
              ))}
            </ol>
            {recommendedCandidates.length > 3 && (
              <button type="button" onClick={() => setShowAllRecommendations((shown) => !shown)}>
                {showAllRecommendations ? '접기' : '더보기'}
              </button>
            )}
          </>
        ) : activeConsultationId ? (
          currentRecommendation?.error ? <p role="alert">{currentRecommendation.error}</p>
            : <p>{recommendation?.message || (passedRecommendation || currentRecommendation
                ? '이 상담일지에 표시할 연결 처방 후보가 없습니다.'
                : '처방 후보를 불러오는 중입니다.')}</p>
        ) : <p>상담일지를 선택하면 저장된 처방 후보를 볼 수 있습니다.</p>}
      </div>

      <h3>선택된 처방 상세정보</h3>
      {selectedPrescription ? (
        <p>선택한 처방: {selectedPrescription}</p>
      ) : (
        <p>아직 선택한 처방이 없습니다.</p>
      )}
        <h3>처방 검색</h3>
        <button
          type="button"
          onClick={() => setShowPrescriptionSearch(true)}
        >
          기업 자료 검색
        </button>

        {showPrescriptionSearch && (
          <div
            style={{
              position: 'fixed',
              inset: 0,
              backgroundColor: 'rgba(0, 0, 0, 0.5)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 1000,
            }}
          >
            <div
              style={{
                backgroundColor: 'white',
                padding: '24px',
                borderRadius: '8px',
                width: '650px',
                maxWidth: '90%',
                maxHeight: '85vh',
                overflowY: 'auto',
              }}
            >
              <h3>기업 자료 검색</h3>

              <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
                <select aria-label="검색 유형" value={catalogType} disabled={catalogLoading} onChange={(event) => {
                  setCatalogType(event.target.value)
                  setCatalogResults([])
                  setCatalogDetail(null)
                  setCatalogOriginal(null)
                  setCatalogError('')
                }}>
                  <option value="prescription">처방</option>
                  <option value="herb">약재</option>
                  <option value="efficacy">효능</option>
                </select>
                <input
                  type="text"
                  value={prescriptionSearchQuery}
                  onChange={(e) => setPrescriptionSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      searchCatalog()
                    }
                  }}
                  placeholder="검색어를 입력해 주세요."
                  style={{
                    flex: 1,
                    padding: '10px',
                    minWidth: 0,
                  }}
                />

                <button
                  type="button"
                  onClick={searchCatalog}
                  disabled={catalogLoading}
                >
                  검색
                </button>
              </div>

              {catalogError && (
                <p style={{ color: 'red' }}>{catalogError}</p>
              )}

              {catalogLoading && <p>불러오는 중...</p>}

              {!catalogLoading && catalogResults.length > 0 && (
                <div style={{ marginBottom: '20px' }}>
                  <h4>검색 결과 ({catalogResults.length}건)</h4>

                  <div
                    style={{
                      maxHeight: '230px',
                      overflowY: 'auto',
                      border: '1px solid #ddd',
                      borderRadius: '5px',
                    }}
                  >
                    {catalogResults.map((item) => (
                      <div
                        key={item.id}
                        style={{
                          padding: '10px',
                          borderBottom: '1px solid #eee',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          gap: '10px',
                        }}
                      >
                        <span>{item.name}</span>

                        <button
                          type="button"
                          disabled={catalogLoading}
                          onClick={() => loadCatalogDetail(item.id)}
                        >
                          상세보기
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {catalogDetail && (
                <div
                  style={{
                    padding: '16px',
                    backgroundColor: '#f5f7f6',
                    border: '1px solid #ddd',
                    borderRadius: '6px',
                    marginBottom: '16px',
                  }}
                >
                  <h4>{catalogDetail.name}</h4>
                  {typeof catalogDetail.connectedToSelectedDisease === 'boolean' && (
                    <p>{catalogDetail.connectedToSelectedDisease ? '선택한 병증과 기업 원본에 연결됨' : '선택한 병증과 등록된 연결 없음'}</p>
                  )}
                  {catalogDetail.description && <p style={{ whiteSpace: 'pre-wrap' }}>{catalogDetail.description}</p>}
                  {catalogDetail.usageText && <p style={{ whiteSpace: 'pre-wrap' }}>용법 · {catalogDetail.usageText}</p>}
                  {catalogDetail.registeredCautionTexts.map((value) => <p key={value}>주의사항 · {value}</p>)}
                  {catalogDetail.messages.map((message) => <p key={message}>{message}</p>)}
                  {catalogDetail.evidence.map((source) => (
                    <p key={source.sourceId}>
                      {source.sourceLocation}{' '}
                      <button type="button" disabled={catalogLoading} onClick={() => loadCatalogOriginal(source.sourceUrl)}>
                        원문 보기
                      </button>
                    </p>
                  ))}
                  {catalogOriginal && <p style={{ whiteSpace: 'pre-wrap' }}>{catalogOriginal.originalText}</p>}
                  {Object.entries({ diseases: '관련 병증', prescriptions: '연결 처방', herbs: '연결 약재', efficacies: '연결 효능' })
                    .filter(([key]) => catalogDetail.relations[key].length > 0)
                    .map(([key, label]) => (
                      <details key={key}>
                        <summary>{label} ({catalogDetail.relations[key].length}건)</summary>
                        <ul>{catalogDetail.relations[key].map((item) => <li key={item.id}>{item.name}</li>)}</ul>
                      </details>
                    ))}
                  {catalogDetail.type === 'prescription' && <>
                    <h4 style={{ marginTop: '20px' }}>약재 구성</h4>

                    {catalogDetail.ingredients.length > 0 ? (
                      <table
                        style={{
                          width: '100%',
                          borderCollapse: 'collapse',
                          textAlign: 'center',
                          marginTop: '10px',
                        }}
                      >
                        <thead>
                          <tr>
                            <th style={{ padding: '8px', borderBottom: '1px solid #ccc' }}>
                              약재명
                            </th>
                            <th style={{ padding: '8px', borderBottom: '1px solid #ccc' }}>
                              규격 및 설명
                            </th>
                            <th style={{ padding: '8px', borderBottom: '1px solid #ccc' }}>
                              용량
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {catalogDetail.ingredients.map((herb) => (
                            <tr key={herb.compositionId}>
                              <td style={{ padding: '8px', borderBottom: '1px solid #eee' }}>
                                {herb.name}
                              </td>
                              <td style={{ padding: '8px', borderBottom: '1px solid #eee' }}>
                                {herb.preparation || '-'}
                              </td>
                              <td style={{ padding: '8px', borderBottom: '1px solid #eee' }}>
                                {formatOriginalDose(herb)}
                                {herb.amount != null && herb.originalDoseInfo && <p>원문 메모: {herb.originalDoseInfo}</p>}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      <p>등록된 약재 정보가 없습니다.</p>
                    )}

                    <button
                      type="button"
                      onClick={applyCatalogPrescription}
                      disabled={catalogLoading}
                      style={{
                        marginTop: '20px',
                        padding: '10px 18px',
                        backgroundColor: '#245c46',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: 'pointer',
                      }}
                    >
                      이 처방 선택
                    </button>
                  </>}
                  {catalogDetail.type === 'herb' && selectedPrescription && (
                    <button type="button" onClick={() => {
                      const { id, name } = catalogDetail
                      setHerbs((current) => [...current.filter((herb) => herb.name.trim()), { id, name, amount: null }])
                      setShowPrescriptionSearch(false)
                    }}>이 약재 추가</button>
                  )}
                </div>
              )}

              <button
                type="button"
                onClick={() => {
                  setShowPrescriptionSearch(false)
                  setCatalogDetail(null)
                  setCatalogOriginal(null)
                  setCatalogResults([])
                  setCatalogError('')
                }}
              >
                닫기
              </button>
            </div>
          </div>
        )}



      <h3>처방 직접입력</h3>
      <button
        type="button"
        onClick={() => setShowDirectInput((prev) => !prev)}
      >
        {showDirectInput ? '직접입력 닫기' : '직접입력'}
      </button>

      {showDirectInput && (
        <div style={{ marginTop: '12px', maxWidth: '700px' }}>
          <input
            type="text"
            value={customPrescription}
            onChange={(e) => setCustomPrescription(e.target.value)}
            placeholder="처방명을 입력해 주세요."
            style={{ padding: '10px', width: '70%' }}
          />

          <button
            type="button"
            onClick={() => {
              if (!customPrescription.trim()) {
                alert('처방명을 입력해 주세요.')
                return
              }

              setSelectedPrescription(customPrescription.trim())
              if (prescriptionSource !== 'manual') {
                setHerbs([{ name: '', amount: '' }])
                setPrescriptionText('')
              }
              setPrescriptionSource('manual')
              setShowDirectInput(false)
            }}
          >
            선택
          </button>
        </div>
      )}
        {selectedPrescription !== null && (
          <div style={{ marginTop: '24px', maxWidth: '700px' }}>
            <h3>처방 구성 입력</h3>

            <label>
              최종 처방명
              <input value={selectedPrescription} onChange={(event) => setSelectedPrescription(event.target.value)} />
            </label>
            <label>
              처방 내용 (선택)
              <textarea
                placeholder="저장할 처방 내용을 직접 입력"
                value={prescriptionText}
                onChange={(event) => setPrescriptionText(event.target.value)}
              />
            </label>

            {herbs.map((herb, index) => (
              <div
                key={index}
                style={{
                  display: 'flex',
                  gap: '8px',
                  marginBottom: '10px',
                  alignItems: 'center',
                }}
              >
                <input
                  type="text"
                  placeholder="약재명"
                  value={herb.name}
                  readOnly={herb.id != null || herb.compositionId != null}
                  onChange={(e) =>
                    updateHerb(index, 'name', e.target.value)
                  }
                  style={{ flex: 2, padding: '10px', minWidth: 0 }}
                />

                <IngredientDoseFields herb={herb} onChange={(field, value) => updateHerb(index, field, value)} />

                <button
                  type="button"
                  onClick={() => removeHerb(index)}
                >
                  삭제
                </button>
              </div>
            ))}

            <button type="button" onClick={addHerb}>
              + 약재 추가
            </button>
          </div>
        )}

      <div style={{ marginTop: '24px' }}>
        <button
          type="button"
          onClick={savePrescription}
          disabled={isSaving || savedPrescription}
        >
          {isSaving
            ? '저장 중...'
            : savedPrescription
              ? '처방전 저장 완료'
              : '처방전 저장'}
        </button>

        <button
          type="button"
          onClick={() => navigate('/today')}
          style={{ marginLeft: '10px' }}
        >
          오늘의 업무로 돌아가기
        </button>
      </div>
    </div>
  )
}

