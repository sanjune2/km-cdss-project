
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

export default function Prescriptions() {
  const location = useLocation()
  const navigate = useNavigate()

  const patient = location.state?.patient
  const consultationId = location.state?.consultationId
  const isNewPrescription = location.pathname === '/prescription/new'

  const [selectedPrescription, setSelectedPrescription] = useState(null)
  const [customPrescription, setCustomPrescription] = useState('')
  const [showDirectInput, setShowDirectInput] = useState(false)
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
    if (isNewPrescription) return

    const loadPrescriptions = async () => {
      try {
        setListError('')

        const response = await fetch(
    'http://127.0.0.1:8000/api/prescriptions',
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

  const [savedPrescription, setSavedPrescription] = useState(false)

  const savePrescription = async () => {
    if (isSaving || savedPrescription) return

    if (!patient?.id || !consultationId) {
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
          'http://127.0.0.1:8000/api/prescriptions',
          {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
            },
          body: JSON.stringify({
            patientId: patient.id,
            consultationId,
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
      `http://127.0.0.1:8000/api/prescriptions/${editPrescription.id}`,
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
  `http://127.0.0.1:8000/api/prescriptions/${record.id}/send`,
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
      `http://127.0.0.1:8000/api/prescriptions/${record.id}`,
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
                      {record.status === '미전송' && (
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
                      {record.status === '미전송' && (
                          <button
                            type="button"
                            onClick={() => sendPrescription(record)}
                            style={{ marginLeft: '8px' }}
                          >
                            전송
                          </button>
                        )}
                      {record.status === '미전송' && (
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

                  <div style={{ marginTop: '20px' }}>
                    <button
                      type="button"
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
  return (
    <div>
      <h2>AI 신규 처방전 작성 및 저장</h2>

      <h3>환자 정보</h3>
      {patient ? (
        <div>
          <p>성명: {patient.name}</p>
          <p>생년월일: {patient.birthDate}</p>
          <p>연락처: {patient.phone}</p>
        </div>
      ) : (
        <p>연결된 환자 정보가 없습니다.</p>
      )}

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
