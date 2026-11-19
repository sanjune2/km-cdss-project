
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

export default function Prescriptions({ currentRole }) {
  const isDesk = currentRole === 'desk'
  const [printCount, setPrintCount] = useState(0)
  const [printHistoryLoading, setPrintHistoryLoading] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  const patient = location.state?.patient
  const consultationId = location.state?.consultationId
  const isNewPrescription = location.pathname === '/prescription/new'

  const [selectedPrescription, setSelectedPrescription] = useState(null)
  const [consultationRecords, setConsultationRecords] = useState([])
  const [patientRecords, setPatientRecords] = useState([])
  const [selectedConsultationId, setSelectedConsultationId] = useState('')
  const [consultationLoadError, setConsultationLoadError] = useState('')
  const [customPrescription, setCustomPrescription] = useState('')
  const [showDirectInput, setShowDirectInput] = useState(false)
  const [showPrescriptionSearch, setShowPrescriptionSearch] = useState(false)
  const [prescriptionSearchQuery, setPrescriptionSearchQuery] = useState('')
  const [catalogResults, setCatalogResults] = useState([])
  const [catalogDetail, setCatalogDetail] = useState(null)
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [catalogError, setCatalogError] = useState('')
  const [herbs, setHerbs] = useState([
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
  const [editPrescription, setEditPrescription] = useState(null)
  const [listError, setListError] = useState('')

  useEffect(() => {
      if (!isDesk || !detailPrescription?.id) {
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
            `/api/prescriptions/${detailPrescription.id}/print-history`,
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
    }, [isDesk, detailPrescription?.id])

  useEffect(() => {
    if (isNewPrescription) return

    const loadPrescriptions = async () => {
      try {
        setListError('')

        const response = await fetch(
    '/api/prescriptions',
      {
            credentials: 'include',
          }
        )

        if (!response.ok) {
          throw new Error('처방전 목록 조회에 실패했습니다.')
        }

        const data = await response.json()
        setPrescriptionRecords(data.records || [])
      } catch (error) {
        console.error('처방전 목록 조회 오류:', error)
        setListError('처방전 목록을 불러오지 못했습니다.')
      }
    }

  loadPrescriptions()
}, [isNewPrescription])

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

    if (
      herbs.length === 0 ||
      herbs.some(
        (herb) =>
          !herb.name.trim() ||
          !herb.amount.trim() ||
          !Number.isFinite(Number(herb.amount)) ||
          Number(herb.amount) <= 0
      )
    ) {
      alert('약재명과 올바른 용량을 입력해 주세요.')
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
            patientId: prescriptionPatient.id,
            consultationId: prescriptionConsultationId,
            prescriptionName: selectedPrescription.trim(),
            herbs: herbs.map((herb) => ({
              name: herb.name.trim(),
              amount: Number(herb.amount),
            })),
          }),
        }
      )

      const data = await response.json()

      if (!response.ok) {
        alert(
          typeof data.detail === 'string'
            ? data.detail
            : '처방전 저장에 실패했습니다.'
        )
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

const updatePrescription = async () => {
  if (!editPrescription || isUpdating) return

  if (!editPrescription.prescriptionName.trim()) {
    alert('처방명을 입력해 주세요.')
    return
  }

  if (
    editPrescription.herbs.length === 0 ||
    editPrescription.herbs.some(
      (herb) =>
        !herb.name.trim() ||
        String(herb.amount).trim() === '' ||
        !Number.isFinite(Number(herb.amount)) ||
        Number(herb.amount) <= 0
    )
  ) {
    alert('약재명과 올바른 용량을 입력해 주세요.')
    return
  }

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
          patientId: editPrescription.patientId,
          consultationId: editPrescription.consultationId,
          prescriptionName: editPrescription.prescriptionName.trim(),
          herbs: editPrescription.herbs.map((herb) => ({
            name: herb.name.trim(),
            amount: Number(herb.amount),
          })),
        }),
      }
    )

    const data = await response.json()

    if (!response.ok) {
      alert(
        typeof data.detail === 'string'
          ? data.detail
          : '처방전 수정에 실패했습니다.'
      )
      return
    }

    setPrescriptionRecords((prev) =>
      prev.map((record) =>
        record.id === data.record.id ? data.record : record
      )
    )

    setDetailPrescription((prev) =>
      prev?.id === data.record.id ? data.record : prev
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
    method: 'POST',
    credentials: 'include',
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
        String(item.id) === String(data.prescriptionId)
          ? { ...item, status: data.status }
          : item
      )
    )

    alert('처방전이 안내데스크로 전송되었습니다.')
  } catch (error) {
    console.error('처방전 전송 오류:', error)
    alert('서버 연결에 실패했습니다.')
  }
}

const deletePrescription = async (record) => {
  if (record.status !== '미전송') return

  const confirmed = window.confirm(
    `${record.patientName} 환자의 처방전을 삭제하시겠습니까?\n삭제한 처방전은 복구할 수 없습니다.`
  )

  if (!confirmed) return

  try {
    const response = await fetch(
      `/api/prescriptions/${record.id}`,
      {
        method: 'DELETE',
        credentials: 'include',
      }
    )

    if (!response.ok) {
      const data = await response.json()
      alert(
        typeof data.detail === 'string'
          ? data.detail
          : '처방전 삭제에 실패했습니다.'
      )
      return
    }

    setPrescriptionRecords((prev) =>
      prev.filter((item) => item.id !== record.id)
    )

    setDetailPrescription((prev) =>
      prev?.id === record.id ? null : prev
    )

    alert('처방전이 삭제되었습니다.')
  } catch (error) {
    console.error('처방전 삭제 오류:', error)
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
                  <td>{record.createdAt?.slice(0, 10)}</td>
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
                      onClick={() => setDetailPrescription(record)}
                    >
                      보기
                    </button>
                      {currentRole !== 'desk' && record.status === '미전송' && (
                          <button
                            type="button"
                            onClick={() =>
                              setEditPrescription({
                                ...record,
                                herbs: record.herbs.map((herb) => ({ ...herb })),
                              })
                            }
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
                      {currentRole !== 'desk' && record.status === '미전송' && (
                          <button
                            type="button"
                            onClick={() => deletePrescription(record)}
                            style={{
                              marginLeft: '8px',
                              color: 'red',
                            }}
                          >
                            삭제
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
                    작성 날짜: {detailPrescription.createdAt?.slice(0, 10)}
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
                        <th>용량(g)</th>
                      </tr>
                    </thead>

                    <tbody>
                      {detailPrescription.herbs.map((herb, index) => (
                        <tr key={index}>
                          <td style={{ padding: '8px' }}>{herb.name}</td>
                          <td style={{ padding: '8px' }}>{herb.amount}</td>
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
                          onClick={async () => {
                            try {
                              const response = await fetch(
                                `/api/prescriptions/${detailPrescription.id}/print`,
                                {
                                  method: 'POST',
                                  credentials: 'include',
                                }
                              )

                              if (!response.ok) {
                                const error = await response.json()
                                throw new Error(
                                  error.detail || '인쇄 요청 기록에 실패했습니다.'
                                )
                              }

                              window.print()
                            } catch (error) {
                              alert(error.message)
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
                        disabled={printHistoryLoading}
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

                      <input
                        type="number"
                        placeholder="용량(g)"
                        min="0"
                        step="0.1"
                        value={herb.amount}
                        onChange={(e) =>
                          setEditPrescription((prev) => ({
                            ...prev,
                            herbs: prev.herbs.map((item, i) =>
                              i === index
                                ? { ...item, amount: e.target.value }
                                : item
                            ),
                          }))
                        }
                        style={{ flex: 1, minWidth: 0, padding: '10px' }}
                      />

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
      setCatalogError('')

      if (!keyword) {
        setCatalogError('검색할 처방명을 입력해 주세요.')
        return
      }

      setCatalogLoading(true)

      try {
        const response = await fetch(
          `/api/prescription-catalog/search?q=${encodeURIComponent(keyword)}`,
          { credentials: 'include' }
        )

        if (!response.ok) {
          throw new Error('처방 검색에 실패했습니다.')
        }

        const data = await response.json()
        setCatalogResults(data.results || [])
      } catch (error) {
        setCatalogError(error.message)
      } finally {
        setCatalogLoading(false)
      }
    }

    const loadCatalogDetail = async (prespId) => {
      setCatalogLoading(true)
      setCatalogError('')

      try {
        const response = await fetch(
          `/api/prescription-catalog/${prespId}`,
          { credentials: 'include' }
        )

        if (!response.ok) {
          throw new Error('처방 상세 조회에 실패했습니다.')
        }

        const data = await response.json()
        setCatalogDetail(data)
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
  setHerbs(
    catalogDetail.herbs?.length
      ? catalogDetail.herbs.map((herb) => ({
          name: herb.name,
          amount: String(herb.amount ?? ''),
        }))
      : [{ name: '', amount: '' }]
  )


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
                        setSelectedPrescription(null)
                        setHerbs([{ name: '', amount: '' }])
                        setCustomPrescription('')
                        setShowDirectInput(false)
                        setShowPrescriptionSearch(false)
                        setCatalogDetail(null)
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
        <p>AI 처방 추천 기능은 아직 연결되지 않았습니다.</p>
        <p>추후 추천 처방 3개와 더보기 기능을 추가할 예정입니다.</p>
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
          처방 검색
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
              <h3>처방 검색</h3>

              <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
                <input
                  type="text"
                  value={prescriptionSearchQuery}
                  onChange={(e) => setPrescriptionSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      searchCatalog()
                    }
                  }}
                  placeholder="검색할 처방명을 입력해 주세요."
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
                  <h4>검색 결과 ({catalogResults.length}건, 최대 50건)</h4>

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
                  <h4>처방 상세 정보</h4>

                  <p><strong>처방명:</strong> {catalogDetail.name}</p>
                  <p><strong>원본 분류:</strong> {catalogDetail.originalCode}</p>
                  <p><strong>처방 설명:</strong> {catalogDetail.description || '-'}</p>
                  <p><strong>용법:</strong> {catalogDetail.usage || '-'}</p>
                  <p><strong>주의사항:</strong> {catalogDetail.cautions || '-'}</p>

                    <h4 style={{ marginTop: '20px' }}>약재 구성</h4>

                    {catalogDetail.herbs?.length > 0 ? (
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
                          {catalogDetail.herbs.map((herb, index) => (
                            <tr key={herb.id ?? index}>
                              <td style={{ padding: '8px', borderBottom: '1px solid #eee' }}>
                                {herb.name}
                              </td>
                              <td style={{ padding: '8px', borderBottom: '1px solid #eee' }}>
                                {herb.specification || '-'}
                              </td>
                              <td style={{ padding: '8px', borderBottom: '1px solid #eee' }}>
                                {herb.amount ?? '-'} {herb.unit || ''}
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
                </div>
              )}

              <button
                type="button"
                onClick={() => {
                  setShowPrescriptionSearch(false)
                  setCatalogDetail(null)
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
              setShowDirectInput(false)
            }}
          >
            선택
          </button>
        </div>
      )}
        {selectedPrescription && (
          <div style={{ marginTop: '24px', maxWidth: '700px' }}>
            <h3>처방 구성 입력</h3>

            <p>처방명: {selectedPrescription}</p>

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
                  onChange={(e) =>
                    updateHerb(index, 'name', e.target.value)
                  }
                  style={{ flex: 2, padding: '10px', minWidth: 0 }}
                />

                <input
                  type="number"
                  placeholder="용량(g)"
                  min="0"
                  step="0.1"
                  value={herb.amount}
                  onChange={(e) =>
                    updateHerb(index, 'amount', e.target.value)
                  }
                  style={{ flex: 1, padding: '10px', minWidth: 0 }}
                />

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
