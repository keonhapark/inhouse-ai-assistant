# 결재·대결 규정

## 제1조(목적)
이 규정은 {{ company }}의 전자결재 결재선과 결재자 부재 시 대결(代決) 위임을 정합니다.

## 제2조(정의)
① "대결"이란 결재권자가 부재 중일 때 위임받은 사람이 대신 결재하는 것을 말합니다.
② "위임자"는 결재 권한을 맡기는 결재권자, "대결자"는 위임받는 사람을 말합니다.

## 제3조(결재선)
① 휴가 신청은 소속 {{ grade:team_leader }}이 결재합니다.
② 경비 정산은 {{ amount:1000000 }} 이하이면 {{ grade:team_leader }}, 초과하면 {{ grade:team_leader }}과 {{ grade:division_head }}이 차례로 결재합니다.
③ 구매 요청은 {{ amount:5000000 }} 이하이면 {{ grade:team_leader }}, 초과하면 {{ grade:team_leader }}과 {{ grade:division_head }}이 차례로 결재합니다.
④ 요청자가 {{ grade:team_leader }}이면 상위 {{ grade:division_head }}이 결재하고, 요청자가 {{ grade:division_head }}이면 {{ grade:ceo }}가 결재합니다.

## 제4조(대결 위임 등록)
① 대결 위임은 위임자 본인이나 {{ role:hr_staff }} 직원이 등록합니다.
② 위임 기간은 {{ delegation:max_period_days }}일을 넘을 수 없습니다.
③ 위임 범위는 양식 종류와 금액 한도로 정합니다.
④ 위임 기간이 {{ delegation:wide_scope.period_days_over }}일을 넘거나, 금액 한도가 {{ delegation:wide_scope.max_amount_over }}원을 넘거나, 모든 양식을 위임하는 경우에는 넓은 위임으로 보고 위임자가 직접 확인한 뒤 등록합니다.

## 제5조(대결의 제한)
① 대결자는 받은 권한을 다시 다른 사람에게 위임할 수 없습니다.
② 대결자는 자기가 요청한 문서를 대결로 결재할 수 없습니다.
③ 위임 범위 밖의 양식이나 금액 한도를 넘는 문서는 대결할 수 없고 위임자의 복귀를 기다립니다.

## 제6조(기록)
대결로 처리한 결재에는 대결자와 원 결재자를 함께 기록하며, 위임자는 복귀 후 대결 내역을 확인합니다.
