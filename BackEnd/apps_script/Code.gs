/**
 * 공들이 신청 폼 → MT 백엔드 연동 스크립트
 *
 * ─────────────────────────────────────────────────────────────
 * [설치 순서]  얼리버드 / 본모집 / 스태프 시트에 각각 설치한다.
 *
 * 1. 폼 응답이 모이는 구글 시트를 열고  확장 프로그램 > Apps Script
 * 2. 이 파일 내용을 붙여넣고 저장
 * 3. 프로젝트 설정 > 스크립트 속성 에 3개를 추가
 *      BACKEND_URL   https://api.example.com        (끝에 / 없이)
 *      INGEST_TOKEN  .env 의 INGEST_TOKEN 과 동일한 값
 *      INTAKE_ROUND  earlybird   ← 얼리버드 시트
 *                    main        ← 본모집 시트
 *                    staff       ← 스태프 시트 (이 값으로 보낸 사람은
 *                                  백엔드에서 자동으로 스태프가 된다)
 * 4. previewMapping 을 실행해 컬럼이 제대로 잡히는지 로그로 확인  ★중요★
 * 5. setupTrigger 를 실행 (권한 승인 필요)
 * 6. syncAll 을 실행해 기존 응답을 전부 밀어넣는다
 *
 * ─────────────────────────────────────────────────────────────
 * [설계 원칙]
 *
 * ● 위치 기반으로 읽는다
 *   '입금 완료 되셨을까요?' 컬럼이 납부자용·미납부자용으로 두 개 있다.
 *   e.namedValues 는 질문 제목이 키라서 제목이 같으면 충돌한다.
 *   그래서 헤더 행과 응답 행을 위치로 맞춰 읽는다.
 *
 * ● 명시적으로 매핑된 항목만 보낸다
 *   FIELD_RULES 에 없는 컬럼은 전송하지 않는다. 새 질문이 추가되어도
 *   모르는 데이터가 서버로 새어 들어가지 않는다.
 *
 * ● 민감 항목은 여기서 잘라낸다
 *   주민등록번호는 개인정보보호법 제24조의2 상 법령 근거 없이 처리할 수 없고,
 *   이 시스템은 이름·전화번호로만 매칭하므로 쓸 일이 전혀 없다.
 *   납부 증빙 스크린샷(드라이브 링크)도 보관하지 않는다.
 *   → DENY_RULES 에 걸리면 전송 대상에서 제외한다.
 *
 * ● 뒤풀이 참가 여부는 폼 문항에서 온다
 *   FIELD_RULES 의 joinsAfterparty 규칙이 그 컬럼을 잡는다. 문항이 없는 폼(스태프
 *   시트 등)에서는 값이 아예 오지 않고, 그때 백엔드는 **기존 값을 건드리지 않는다** —
 *   관리자가 화면에서 켜 둔 것이 재제출 한 번으로 풀려서는 안 되기 때문이다.
 *
 * ● 스태프 시트도 같은 규칙을 쓴다
 *   질문 구성이 참가자 폼과 거의 같아서 FIELD_RULES 를 그대로 태운다.
 *   다른 점은 두 가지뿐이고, 둘 다 규칙을 고치지 않아도 된다 —
 *   총학생회비 질문이 없어 isCouncilMember 가 비고(스태프는 요금 구분이
 *   '스태프'라 쓰이지 않는다), 참가비 안내문에 '스태프'가 적혀 있지만
 *   그 컬럼은 어느 규칙에도 걸리지 않아 전송되지 않는다.
 *   스태프인지는 컬럼이 아니라 INTAKE_ROUND=staff 하나로 정해진다.
 */

var PROPS = PropertiesService.getScriptProperties();
var TZ = 'Asia/Seoul';

/** 헤더 비교용 정규화: 공백·줄바꿈 제거 + 영문 소문자화 */
function normalizeHeader_(text) {
  return String(text == null ? '' : text).replace(/\s+/g, '').toLowerCase();
}

function startsWith_(needle) {
  return function (h) { return h.indexOf(needle) === 0; };
}

function contains_(needle) {
  return function (h) { return h.indexOf(needle) !== -1; };
}

function containsAll_() {
  var needles = Array.prototype.slice.call(arguments);
  return function (h) {
    for (var i = 0; i < needles.length; i++) {
      if (h.indexOf(needles[i]) === -1) return false;
    }
    return true;
  };
}

/**
 * 절대 전송하지 않는 컬럼.
 * DENY 가 FIELD_RULES 보다 먼저 평가된다.
 */
var DENY_RULES = [
  { reason: '주민등록번호 (개인정보보호법 제24조의2)', test: contains_('주민등록') },
  { reason: '주민번호', test: contains_('주민번호') },
  { reason: '납부 증빙 스크린샷 (드라이브 링크)', test: contains_('스크린샷') },
  { reason: '파일 업로드 항목', test: contains_('업로드해주세요') },
];

/**
 * 컬럼 → 백엔드 필드 매핑. 위에서부터 먼저 맞는 규칙이 적용된다.
 *
 * 헤더가 긴 안내문이라 단순 포함 검사는 위험하다. 예를 들어
 * '입금자명 : 성명+전화번호 뒷자리...' 에는 '성명'과 '전화번호'가 모두 들어 있어
 * 이름/전화번호 컬럼으로 오인될 수 있다. 그래서 앞부분 일치(startsWith)를
 * 우선 쓰고, 필요한 경우 두 개 이상의 키워드를 함께 요구한다.
 */
//
// 이번 폼('[이과대 X 공과대] 이공공이(2002) 참여자 모집')의 열은 이렇다. 헤더의 예시 문구와
// 줄바꿈은 normalizeHeader_ 가 지우므로 앞부분만 본다.
//
//   타임스탬프 · 개인정보·초상권 동의서 · 이름 · 학과 · 학번(예시…) · 전화번호(예시…) ·
//   총학생회비 납부여부 · 참가비 입금(안내문…) · 1부 교류전 - 조장 지원 여부 ·
//   솔로파티 참가 여부 · 솔로파티 사전 참여비 · 성별 · 태어난 년도 · 닉네임
//
var FIELD_RULES = [
  { field: 'submittedAt',     test: startsWith_('타임스탬프') },
  { field: 'name',            test: function (h) { return h === '이름' || h === '성명'; } },
  { field: 'studentId',       test: startsWith_('학번') },
  { field: 'gender',          test: startsWith_('성별') },
  { field: 'phone',           test: startsWith_('전화번호') },
  { field: 'emergencyPhone',  test: startsWith_('비상') },
  // '학과' 한 단어짜리 열과 '소속 학과'. 동의서 본문에도 '학과'가 들어 있어 startsWith 로만 본다.
  { field: 'department',      test: function (h) { return h.indexOf('소속') === 0 || h.indexOf('학과') === 0; } },

  // '지병이 있으십니까?' 와 '지병 증상 발현 시 조치사항' 이 둘 다 '지병'을 포함한다.
  { field: 'healthAction',    test: contains_('조치사항') },
  { field: 'hasHealthIssue',  test: containsAll_('지병', '있으십니까') },
  { field: 'healthNote',      test: startsWith_('병명') },

  // '식재료 알레르기 유무'(응답) 와 '식품 알레르기가 있는 참가자는...'(안내 확인)를 구분
  { field: 'allergy',         test: startsWith_('식재료알레르기') },

  // '총학생회비 납부여부' — 앞부분 일치. '참가비 입금' 열의 안내문에도 '총학생회비 납부자'가
  // 들어 있으므로 contains 로 보면 그 열까지 잡힌다.
  { field: 'isCouncilMember', test: function (h) { return h.indexOf('총학생회비') === 0 || containsAll_('총학생회비', '납부하셨')(h); } },

  // 본인이 '입금했다'고 답한 값. 이번 폼은 '참가비 입금(안내문…)', 지난 폼은 '입금 완료…'.
  { field: 'declaredPaid',    test: function (h) { return h.indexOf('참가비입금') === 0 || h.indexOf('입금완료') === 0; }, multi: true },

  // 1부 교류전 조장 지원 여부 — 조 편성 때 '하고 싶다'를 먼저 앉힌다.
  { field: 'leaderPreference', test: contains_('조장') },
  // 닉네임 · 태어난 년도 — 솔로파티와 명찰에 쓴다.
  { field: 'nickname',        test: function (h) { return h.indexOf('닉네임') === 0 || h.indexOf('별명') === 0; } },
  { field: 'birthYear',       test: function (h) { return h.indexOf('태어난') === 0 || h.indexOf('출생') === 0; } },

  // 솔로파티(뒤풀이) 관련 열이 둘이다 — '참가 여부' 와 '사전 참여비'(안내를 확인했는가).
  // 둘 다 '솔로파티'를 품고 있으므로 구체적인 쪽(참여비)을 먼저 건다.
  { field: 'afterpartyFeeAcknowledged', test: containsAll_('솔로파티', '참여비') },
  // 이 값이 켜지면 참가비에 솔로파티비가 얹히고, 2부 출석 회차의 대상이 된다.
  { field: 'joinsAfterparty', test: function (h) { return (h.indexOf('솔로파티') !== -1 || h.indexOf('뒤풀이') !== -1) && h.indexOf('참여비') === -1; } },

  { field: 'portraitConsent', test: contains_('초상') },
];

// ---------------------------------------------------------------------------

function getConfig_() {
  var backendUrl = PROPS.getProperty('BACKEND_URL');
  var token = PROPS.getProperty('INGEST_TOKEN');
  var round = PROPS.getProperty('INTAKE_ROUND');

  if (!backendUrl || !token) {
    throw new Error('스크립트 속성에 BACKEND_URL 과 INGEST_TOKEN 을 먼저 설정하세요.');
  }
  // 이번 행사는 참가자 시트가 하나라 'main' 이면 된다. 스태프 시트를 따로 두면 'staff'.
  if (round !== 'earlybird' && round !== 'main' && round !== 'staff') {
    throw new Error("스크립트 속성 INTAKE_ROUND 를 'main' (참가자 시트) 또는 'staff' (스태프 시트) 로 설정하세요.");
  }
  var base = backendUrl.replace(/\/+$/, '');
  return {
    base: base,
    url: base + '/api/ingest/form',
    pingUrl: base + '/api/ingest/ping',
    healthUrl: base + '/api/health',
    token: token,
    round: round,
  };
}

/**
 * ★ previewMapping 과 함께 가장 먼저 실행할 것 ★
 *
 * 백엔드까지 실제로 닿는지, 토큰이 맞는지 단계별로 확인한다.
 * Apps Script 는 브라우저가 아니라 구글 서버에서 요청을 보내기 때문에,
 * Cloudflare 봇 차단에 걸려 403 이 나는 경우가 흔하다.
 */
function testConnection() {
  var config = getConfig_();
  Logger.log('대상: %s (회차: %s)', config.base, config.round);

  // 1) 네트워크 · Cloudflare 통과 여부 (인증 불필요)
  var health = UrlFetchApp.fetch(config.healthUrl, { muteHttpExceptions: true });
  Logger.log('[1] health  %s  %s', health.getResponseCode(), health.getContentText().slice(0, 120));
  if (health.getResponseCode() === 403) {
    Logger.log('    → Cloudflare 가 막고 있습니다. WAF 에서 /api/ 경로를 예외 처리하거나');
    Logger.log('      Bot Fight Mode 를 끄세요. (브라우저에서는 되는데 여기서만 403 이면 이것입니다)');
    return;
  }
  if (health.getResponseCode() !== 200) {
    Logger.log('    → BACKEND_URL 을 확인하세요.');
    return;
  }

  // 2) 토큰이 맞는지 (저장은 하지 않는 엔드포인트)
  var ping = UrlFetchApp.fetch(config.pingUrl, {
    method: 'post',
    contentType: 'application/json; charset=utf-8',
    headers: { 'X-Ingest-Token': config.token },
    payload: JSON.stringify({ text: '연결 테스트' }),
    muteHttpExceptions: true,
  });
  Logger.log('[2] ping    %s  %s', ping.getResponseCode(), ping.getContentText().slice(0, 200));

  if (ping.getResponseCode() === 401) {
    Logger.log('    → INGEST_TOKEN 이 백엔드 .env 값과 다릅니다.');
  } else if (ping.getResponseCode() === 200) {
    Logger.log('    → 연결·인증 모두 정상입니다. previewMapping 을 실행하세요.');
  }
}

function getResponseSheet_() {
  return SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
}

/** 헤더 행을 읽어 '열 인덱스 → 필드명' 표를 만든다. */
function buildColumnMap_(headerRow) {
  var map = { fields: {}, multi: {}, denied: [], unmapped: [] };

  for (var col = 0; col < headerRow.length; col++) {
    var raw = headerRow[col];
    if (raw === '' || raw == null) continue;
    var h = normalizeHeader_(raw);

    var deniedBy = null;
    for (var d = 0; d < DENY_RULES.length; d++) {
      if (DENY_RULES[d].test(h)) { deniedBy = DENY_RULES[d].reason; break; }
    }
    if (deniedBy) {
      map.denied.push({ col: col, header: String(raw), reason: deniedBy });
      continue;
    }

    var matched = null;
    for (var r = 0; r < FIELD_RULES.length; r++) {
      var rule = FIELD_RULES[r];
      if (!rule.test(h)) continue;
      if (rule.multi) {
        if (!map.multi[rule.field]) map.multi[rule.field] = [];
        map.multi[rule.field].push(col);
        matched = rule.field;
        break;
      }
      if (map.fields[rule.field] === undefined) {
        map.fields[rule.field] = col;
        matched = rule.field;
        break;
      }
    }
    if (!matched) map.unmapped.push({ col: col, header: String(raw) });
  }
  return map;
}

function cellToString_(value) {
  if (value == null) return '';
  if (Object.prototype.toString.call(value) === '[object Date]') {
    return Utilities.formatDate(value, TZ, "yyyy-MM-dd'T'HH:mm:ss");
  }
  return String(value).trim();
}

/** 응답 행 하나를 백엔드 필드 형태로 바꾼다. */
function rowToValues_(row, map, round) {
  var values = { intakeRound: round };

  Object.keys(map.fields).forEach(function (field) {
    var text = cellToString_(row[map.fields[field]]);
    if (text !== '') values[field] = text;
  });

  // 같은 제목의 컬럼이 여러 개인 경우 — 비어 있지 않은 첫 값을 쓴다
  Object.keys(map.multi).forEach(function (field) {
    var columns = map.multi[field];
    for (var i = 0; i < columns.length; i++) {
      var text = cellToString_(row[columns[i]]);
      if (text !== '') { values[field] = text; break; }
    }
  });

  return values;
}

// ---------------------------------------------------------------------------
// 실행 함수
// ---------------------------------------------------------------------------

/**
 * ★ 설치 후 가장 먼저 실행할 것 ★
 * 각 컬럼이 어떤 필드로 잡히는지, 무엇이 제외되는지 로그로 보여준다.
 */
function previewMapping() {
  var config = getConfig_();
  var sheet = getResponseSheet_();
  var data = sheet.getDataRange().getValues();
  if (data.length === 0) { Logger.log('시트가 비어 있습니다.'); return; }

  var map = buildColumnMap_(data[0]);

  Logger.log('=== 접수 회차: %s ===', config.round);
  if (config.round === 'staff') {
    Logger.log('이 시트의 응답은 백엔드에서 자동으로 스태프가 됩니다 (참가비도 스태프 금액).');
  }
  Logger.log('--- 백엔드로 보내는 항목 ---');
  Object.keys(map.fields).forEach(function (field) {
    Logger.log('  %s  ←  %s열  "%s"', field, map.fields[field] + 1,
               String(data[0][map.fields[field]]).split('\n')[0]);
  });
  Object.keys(map.multi).forEach(function (field) {
    Logger.log('  %s  ←  %s열 (여러 컬럼 병합)', field,
               map.multi[field].map(function (c) { return c + 1; }).join(', '));
  });

  Logger.log('--- 의도적으로 제외 (전송 안 함) ---');
  map.denied.forEach(function (item) {
    Logger.log('  %s열  "%s"  → %s', item.col + 1,
               String(item.header).split('\n')[0], item.reason);
  });

  Logger.log('--- 매핑 규칙 없음 (전송 안 함) ---');
  map.unmapped.forEach(function (item) {
    Logger.log('  %s열  "%s"', item.col + 1, String(item.header).split('\n')[0].slice(0, 50));
  });

  var required = ['name', 'phone'];
  var missing = required.filter(function (f) { return map.fields[f] === undefined; });
  if (missing.length) {
    Logger.log('!!! 필수 항목을 찾지 못했습니다: %s — FIELD_RULES 를 조정하세요.', missing.join(', '));
  } else {
    Logger.log('필수 항목(이름, 전화번호) 확인 완료.');
  }
}

/** 폼 제출 트리거를 설치한다. 중복 설치를 막기 위해 기존 트리거는 제거한다. */
function setupTrigger() {
  getConfig_();
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === 'onFormSubmitToBackend') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger('onFormSubmitToBackend')
    .forSpreadsheet(spreadsheet)
    .onFormSubmit()
    .create();
  Logger.log('트리거 설치 완료');
}

/** 폼 제출 시 호출된다. */
function onFormSubmitToBackend(e) {
  var config = getConfig_();
  var sheet = (e && e.range) ? e.range.getSheet() : getResponseSheet_();
  var rowNumber = (e && e.range) ? e.range.getRow() : sheet.getLastRow();

  var lastColumn = sheet.getLastColumn();
  var header = sheet.getRange(1, 1, 1, lastColumn).getValues()[0];
  var row = sheet.getRange(rowNumber, 1, 1, lastColumn).getValues()[0];

  var map = buildColumnMap_(header);
  postToBackend_({
    row: rowNumber,
    sheet: config.round,
    values: rowToValues_(row, map, config.round),
  }, config);
}

/** 시트 전체를 백엔드로 밀어넣는다 (최초 1회 / 누락 복구용). */
function syncAll() {
  var config = getConfig_();
  var sheet = getResponseSheet_();
  var data = sheet.getDataRange().getValues();
  if (data.length < 2) { Logger.log('보낼 응답이 없습니다.'); return; }

  var map = buildColumnMap_(data[0]);
  var rows = [];
  for (var i = 1; i < data.length; i++) {
    var values = rowToValues_(data[i], map, config.round);
    if (!values.name && !values.phone) continue;   // 빈 행 건너뛰기
    rows.push({ row: i + 1, sheet: config.round, values: values });
  }

  // 한 번에 너무 많이 보내지 않도록 100건씩 나눈다.
  for (var k = 0; k < rows.length; k += 100) {
    postToBackend_({ rows: rows.slice(k, k + 100) }, config);
  }
  Logger.log('동기화 완료: %s건 (%s)', rows.length, config.round);
}

function postToBackend_(payload, config) {
  config = config || getConfig_();
  var response = UrlFetchApp.fetch(config.url, {
    method: 'post',
    contentType: 'application/json; charset=utf-8',
    headers: { 'X-Ingest-Token': config.token },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  var code = response.getResponseCode();
  var body = response.getContentText();
  if (code < 200 || code >= 300) {
    Logger.log('전송 실패 %s: %s', code, body);
    throw new Error('백엔드 전송 실패 (' + code + ')');
  }
  Logger.log('전송 성공: %s', body);
}
