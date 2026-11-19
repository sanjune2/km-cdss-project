

import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'


export default function Consultation() {
  const location = useLocation()
  const navigate = useNavigate()

  const patient = location.state?.patient
  const fromToday = location.state?.source === 'today'
  const [symptoms, setSymptoms] = useState('')
  const [additionalNotes, setAdditionalNotes] = useState('')
  const [savedConsultation, setSavedConsultation] = useState(false)
  const [savedConsultationId, setSavedConsultationId] = useState(null)

  const [patients, setPatients] = useState([])
  const [selectedPatientId, setSelectedPatientId] = useState('')
  useEffect(() => {
    const fetchPatients = async () => {
      try {
        const response = await fetch('/api/waiting', {
          credentials: 'include',
        })

        if (!response.ok) {
          throw new Error('진료 중인 환자 목록 조회 실패')
        }

        const data = await response.json()

        const consultingPatients = (data.patients || []).filter(
            (patient) =>
                patient.status === '진료중' ||
                patient.status === '진료 중'
        )

        setPatients(consultingPatients)
      } catch (error) {
        console.error('환자 목록 조회 오류:', error)
      }
    }

    fetchPatients()
  }, [])

  const [analysisMessage, setAnalysisMessage] = useState('')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analysisError, setAnalysisError] = useState('')


  const [aiCandidates, setAiCandidates] = useState([])

  const [evidenceCandidate, setEvidenceCandidate] = useState(null)
  const [showAllCandidates, setShowAllCandidates] = useState(false)
  const [selectedCandidates, setSelectedCandidates] = useState([])
  const [customCandidate, setCustomCandidate] = useState('')

  const visibleCandidates = showAllCandidates
      ? aiCandidates
      : aiCandidates.slice(0, 3)

  const toggleAiCandidate = (name) => {
    setSelectedCandidates((prev) =>
        prev.includes(name)
            ? prev.filter((candidate) => candidate !== name)
            : [...prev, name]
    )
  }


  const addCustomCandidate = () => {
    const name = customCandidate.trim()

    if (!name) {
      alert('병증명을 입력해 주세요.')
      return
    }

    if (selectedCandidates.includes(name)) {
      alert('이미 추가된 병증입니다.')
      return
    }

    setSelectedCandidates((prev) => [...prev, name])
    setCustomCandidate('')
  }

  const removeCandidate = (name) => {
    setSelectedCandidates((prev) =>
        prev.filter((candidate) => candidate !== name)
    )
  }

  const analyzeSymptoms = async () => {
    if (!symptoms.trim()) {
      alert('증상을 먼저 입력해 주세요.')
      return
    }


    setIsAnalyzing(true)
    setAnalysisError('')
    setAnalysisMessage('')
    setAiCandidates([])
    setShowAllCandidates(false)

    try {
      const response = await fetch('/api/diagnosis/recommend', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          symptoms: symptoms.trim(),
        }),
      })

      if (!response.ok) {
        throw new Error('서버 요청에 실패했습니다.')
      }

      const data = await response.json()

      setAiCandidates(
          Array.isArray(data.candidates) ? data.candidates : []
      )
      setAnalysisMessage(data.message || '')
    } catch (error) {
      setAnalysisError(error.message || '분석 중 오류가 발생했습니다.')
    } finally {
      setIsAnalyzing(false)
    }
  }


  const validateConsultation = async () => {
    if (!patient?.id) {
      alert('환자 정보가 없습니다.')
      return
    }

    if (!symptoms.trim()) {
      alert('증상을 입력해 주세요.')
      return
    }

    try {
      const response = await fetch(
          '/api/consultations',
          {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              patientId: patient.id,
              symptoms: symptoms.trim(),
              selectedCandidates,
              additionalNotes: additionalNotes.trim(),
            }),
          }
      )

      const data = await response.json()

      if (!response.ok) {
        alert(
            typeof data.detail === 'string'
                ? data.detail
                : '상담일지 저장에 실패했습니다.'
        )
        return
      }

      setSavedConsultationId(data.record.id)
      setSavedConsultation(true)
      alert('상담일지가 저장되었습니다.')
    } catch (error) {
      console.error('상담일지 저장 오류:', error)
      alert('서버 연결에 실패했습니다.')
    }
  }

  return (
      <div>
        <h2>상담일지 작성</h2>

        {fromToday && patient ? (
            <div>
              <h3>환자 정보</h3>

              <p>성명: {patient.name}</p>
              <p>생년월일: {patient.birthDate}</p>
              <p>연락처: {patient.phone}</p>
              <p>주소: {patient.address}</p>

              <h4>보호자 정보 (선택)</h4>
              <p>보호자 이름: {patient.guardianName || '-'}</p>
              <p>관계: {patient.guardianRelation || '-'}</p>
              <p>보호자 연락처: {patient.guardianPhone || '-'}</p>

              <h3>증상 입력</h3>

              <textarea
                  value={symptoms}
                  onChange={(e) => setSymptoms(e.target.value)}
                  placeholder="환자가 설명한 증상을 입력해 주세요."
                  rows={6}
                  style={{
                    width: '100%',
                    maxWidth: '700px',
                    padding: '12px',
                    boxSizing: 'border-box',
                    resize: 'vertical',
                  }}
              />

              <h3>AI 병증 후보 추천</h3>

              <p>
                입력한 증상을 분석하여 관련 병증 후보를 표시합니다.
              </p>

              <div
                  style={{
                    border: '1px solid #ddd',
                    borderRadius: '8px',
                    padding: '16px',
                    maxWidth: '700px',
                  }}
              >

                {aiCandidates.length === 0 ? (
                    <p>아직 AI 분석 결과가 없습니다.</p>
                ) : (
                    <div>
                      {visibleCandidates.map((candidate) => (
                          <div
                              key={candidate.name}
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '12px',
                                marginBottom: '12px',
                              }}
                          >
                            <label>
                              <input
                                  type="checkbox"
                                  checked={selectedCandidates.includes(candidate.name)}
                                  onChange={() => toggleAiCandidate(candidate.name)}
                              />
                              {' '}{candidate.name}
                            </label>

                            <button
                                type="button"
                                onClick={() => setEvidenceCandidate(candidate)}
                            >
                              근거보기
                            </button>

                          </div>
                      ))}
                    </div>
                )}

                <button
                    type="button"
                    onClick={analyzeSymptoms}
                    disabled={isAnalyzing}
                >
                  {isAnalyzing ? '분석 중...' : 'AI 병증 분석'}
                </button>
                {analysisMessage && (
                    <p>{analysisMessage}</p>
                )}

                {analysisError && (
                    <p style={{color: 'red'}}>
                      {analysisError}
                    </p>
                )}

                <div style={{marginTop: '16px'}}>
                  {aiCandidates.length > 3 && (
                      <button
                          type="button"
                          onClick={() => setShowAllCandidates((prev) => !prev)}
                      >
                        {showAllCandidates ? '접기' : '더보기'}
                      </button>
                  )}
                </div>
              </div>


              <h3>병증 직접 입력</h3>

              <div style={{display: 'flex', gap: '8px', maxWidth: '700px'}}>
                <input
                    type="text"
                    value={customCandidate}
                    onChange={(e) => setCustomCandidate(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        addCustomCandidate()
                      }
                    }}
                    placeholder="병증명을 직접 입력해 주세요."
                    style={{
                      padding: '10px',
                      flex: 1,
                      minWidth: 0,
                    }}
                />

                <button type="button" onClick={addCustomCandidate}>
                  추가
                </button>
              </div>

              <h3>선택한 병증</h3>

              {selectedCandidates.length === 0 ? (
                  <p>선택한 병증이 없습니다.</p>
              ) : (
                  <div style={{maxWidth: '700px'}}>
                    {selectedCandidates.map((candidate) => (
                        <div
                            key={candidate}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              padding: '10px',
                              border: '1px solid #ddd',
                              borderRadius: '6px',
                              marginBottom: '8px',
                            }}
                        >
                          <span>{candidate}</span>

                          <button
                              type="button"
                              onClick={() => removeCandidate(candidate)}
                          >
                            삭제
                          </button>
                        </div>
                    ))}
                  </div>
              )}

              <h3>추가 기록</h3>

              <textarea
                  value={additionalNotes}
                  onChange={(e) => setAdditionalNotes(e.target.value)}
                  placeholder="한의사가 추가로 기록할 내용을 입력해 주세요."
                  rows={5}
                  style={{
                    width: '100%',
                    maxWidth: '700px',
                    padding: '12px',
                    boxSizing: 'border-box',
                    resize: 'vertical',
                  }}
              />

              <div style={{marginTop: '20px', marginBottom: '12px'}}>
                <button
                    type="button"
                    onClick={validateConsultation}
                    disabled={savedConsultation}
                >
                  {savedConsultation ? '상담일지 저장 완료' : '상담일지 저장'}
                </button>
              </div>
              {savedConsultation && (
                  <div style={{marginTop: '12px', marginBottom: '12px'}}>
                    <button
                        type="button"
                        onClick={() =>
                            navigate('/prescription/new', {
                              state: {
                                patient,
                                consultationId: savedConsultationId,
                              },
                            })
                        }
                    >
                      AI 신규 처방전 작성 및 저장
                    </button>
                  </div>
              )}
              <button onClick={() => navigate('/today')}>
                오늘의 업무로 돌아가기
              </button>

              {evidenceCandidate && (
                  <div
                      style={{
                        position: 'fixed',
                        inset: 0,
                        backgroundColor: 'rgba(0, 0, 0, 0.5)',
                        display: 'flex',
                        justifyContent: 'center',
                        alignItems: 'center',
                        zIndex: 1000,
                      }}
                  >
                    <div
                        role="dialog"
                        aria-modal="true"
                        aria-label="병증 근거 상세"
                        style={{
                          backgroundColor: 'white',
                          padding: '24px',
                          borderRadius: '10px',
                          width: '90%',
                          maxWidth: '550px',
                        }}
                    >
                      <h3>병증 근거 상세</h3>

                      <p>병증명: {evidenceCandidate.name}</p>

                      <h4>근거 내용</h4>
                      <p>
                        {evidenceCandidate.evidence ||
                            '연결된 근거 자료가 없습니다.'}
                      </p>

                      {evidenceCandidate.sourceUrl && (
                          <p>
                            <a
                                href={evidenceCandidate.sourceUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                              기업 데이터 원문 보기
                            </a>
                          </p>
                      )}

                      <button
                          type="button"
                          onClick={() => setEvidenceCandidate(null)}
                      >
                        닫기
                      </button>
                    </div>
                  </div>
              )}

            </div>
        ) : (
            <div>
              <h3>진료 중인 환자 선택</h3>

              {patients.length === 0 ? (
                  <p>현재 진료 중인 환자가 없습니다.</p>
              ) : (
                  <div>
                    <select
                        value={selectedPatientId}
                        onChange={(e) => setSelectedPatientId(e.target.value)}
                    >
                      <option value="">환자를 선택해 주세요.</option>

                      {patients.map((patient) => (
                          <option key={patient.id} value={patient.id}>
                            {patient.name}
                          </option>
                      ))}
                    </select>

                    <button
                        type="button"
                        disabled={!selectedPatientId}
                        onClick={() => {
                          const selectedPatient = patients.find(
                              (patient) =>
                                  String(patient.id) === String(selectedPatientId)
                          )

                          if (!selectedPatient) return

                          navigate('/consultation', {
                            state: {
                              patient: selectedPatient,
                              source: 'today',
                            },
                          })
                        }}
                    >
                      상담일지 작성
                    </button>
                  </div>
              )}
            </div>
        )}
      </div>
    )
  }



