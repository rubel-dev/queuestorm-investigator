from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from math import isclose

from app.models import (
    AnalysisResponse,
    AnalyzeTicketRequest,
    CaseType,
    Department,
    EvidenceVerdict,
    Severity,
    Transaction,
    TransactionStatus,
    TransactionType,
    UserType,
)


HIGH_VALUE_AMOUNT = 10_000
CRITICAL_VALUE_AMOUNT = 50_000
AMBIGUITY_GAP = 1.75


BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


CASE_KEYWORDS: dict[CaseType, tuple[str, ...]] = {
    CaseType.phishing_or_social_engineering: (
        "otp",
        "pin",
        "password",
        "passcode",
        "verification code",
        "secret code",
        "credential",
        "scam",
        "fraud",
        "phishing",
        "fake call",
        "suspicious call",
        "suspicious sms",
        "login link",
        "account risk",
        "account hacked",
        "hack",
        "ওটিপি",
        "otp",
        "পিন",
        "পাসওয়ার্ড",
        "পাসওয়ার্ড",
        "গোপন কোড",
        "প্রতারক",
        "প্রতারণা",
        "ভুয়া",
        "ভুয়া",
        "স্ক্যাম",
        "ফিশিং",
        "লিংক",
        "link dise",
        "fake number",
        "pin chay",
        "otp chay",
        "password chay",
    ),
    CaseType.duplicate_payment: (
        "duplicate",
        "twice",
        "two times",
        "double",
        "charged twice",
        "paid twice",
        "same payment",
        "again charged",
        "দুইবার",
        "দুই বার",
        "ডাবল",
        "একই পেমেন্ট",
        "duibar",
        "dui bar",
        "double payment",
    ),
    CaseType.merchant_settlement_delay: (
        "settlement",
        "settled",
        "merchant settlement",
        "merchant balance",
        "merchant account",
        "merchant payout",
        "payout",
        "not settled",
        "settlement delay",
        "মার্চেন্ট",
        "সেটেলমেন্ট",
        "সেটেল",
        "পেমেন্ট পাইনি",
        "merchant taka aseni",
        "settlement aseni",
    ),
    CaseType.agent_cash_in_issue: (
        "cash in",
        "cash-in",
        "cashin",
        "agent cash",
        "agent deposit",
        "cash deposit",
        "deposit not reflected",
        "balance not added",
        "balance not updated",
        "not reflected",
        "ক্যাশ ইন",
        "ক্যাশইন",
        "এজেন্ট",
        "জমা",
        "ব্যালেন্সে আসেনি",
        "balance e aseni",
        "cash in aseni",
        "agent er kache",
    ),
    CaseType.wrong_transfer: (
        "wrong number",
        "wrong person",
        "wrong recipient",
        "wrong transfer",
        "wrong account",
        "mistakenly sent",
        "sent by mistake",
        "sent to wrong",
        "by mistake",
        "didn't get it",
        "did not get it",
        "didn't receive",
        "did not receive",
        "recipient did not receive",
        "ভুল নম্বর",
        "ভুল নাম্বার",
        "ভুলে পাঠিয়েছি",
        "ভুলে পাঠিয়েছি",
        "ভুল ট্রান্সফার",
        "vul number",
        "bhul number",
        "wrong num",
        "bhule pathaisi",
        "vule pathaisi",
    ),
    CaseType.payment_failed: (
        "payment failed",
        "failed payment",
        "transaction failed",
        "failed but deducted",
        "deducted but failed",
        "balance deducted",
        "money deducted",
        "amount deducted",
        "merchant did not receive",
        "payment did not go",
        "পেমেন্ট ফেইল",
        "পেমেন্ট ফেল",
        "টাকা কেটে গেছে",
        "ব্যালেন্স কেটে গেছে",
        "ফেইল",
        "ফেল",
        "kete geche",
        "kete gese",
        "taka keteche",
        "payment fail",
        "balance kata",
    ),
    CaseType.refund_request: (
        "refund",
        "return my money",
        "money back",
        "reverse",
        "reversal",
        "chargeback",
        "টাকা ফেরত",
        "রিফান্ড",
        "ফেরত চাই",
        "taka ferot",
        "refund chai",
        "money ferot",
    ),
}


DEPARTMENT_BY_CASE: dict[CaseType, Department] = {
    CaseType.wrong_transfer: Department.dispute_resolution,
    CaseType.payment_failed: Department.payments_ops,
    CaseType.refund_request: Department.customer_support,
    CaseType.duplicate_payment: Department.payments_ops,
    CaseType.merchant_settlement_delay: Department.merchant_operations,
    CaseType.agent_cash_in_issue: Department.agent_operations,
    CaseType.phishing_or_social_engineering: Department.fraud_risk,
    CaseType.other: Department.customer_support,
}


TRANSACTION_TYPES_BY_CASE: dict[CaseType, set[TransactionType]] = {
    CaseType.wrong_transfer: {TransactionType.transfer},
    CaseType.payment_failed: {TransactionType.payment, TransactionType.transfer},
    CaseType.refund_request: {
        TransactionType.payment,
        TransactionType.transfer,
        TransactionType.refund,
        TransactionType.cash_in,
        TransactionType.cash_out,
    },
    CaseType.duplicate_payment: {TransactionType.payment},
    CaseType.merchant_settlement_delay: {TransactionType.settlement},
    CaseType.agent_cash_in_issue: {TransactionType.cash_in},
    CaseType.other: set(),
    CaseType.phishing_or_social_engineering: set(),
}


CASE_PRIORITY = [
    CaseType.phishing_or_social_engineering,
    CaseType.duplicate_payment,
    CaseType.wrong_transfer,
    CaseType.merchant_settlement_delay,
    CaseType.agent_cash_in_issue,
    CaseType.payment_failed,
    CaseType.refund_request,
    CaseType.other,
]


@dataclass(frozen=True)
class TimeHint:
    hour: int
    minute: int | None = None


@dataclass
class ComplaintSignals:
    text: str
    case_scores: dict[CaseType, float]
    amounts: list[float]
    transaction_ids: set[str]
    counterparties: set[str]
    time_hints: list[TimeHint]
    status_words: set[str]
    risk_words: set[str]
    reason_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TransactionMatch:
    transaction: Transaction | None
    score: float
    reason_codes: list[str]
    ambiguous: bool = False
    conflicting: bool = False


def analyze_ticket(payload: AnalyzeTicketRequest) -> AnalysisResponse:
    transactions = payload.transaction_history or []
    signals = extract_complaint_signals(payload.complaint)

    initial_case_type, classification_reasons = classify_case(signals, payload, transactions)
    match = find_relevant_transaction(signals, initial_case_type, transactions)
    case_type, case_reasons = refine_case_type(
        initial_case_type, signals, match, payload, transactions
    )

    if case_type != initial_case_type:
        match = find_relevant_transaction(signals, case_type, transactions)

    verdict, verdict_reasons = determine_verdict(case_type, signals, match, transactions)
    severity = determine_severity(case_type, match.transaction, verdict, signals, match)
    department = determine_department(case_type, payload, severity, verdict, match)
    human_review_required = should_require_human_review(
        case_type=case_type,
        severity=severity,
        verdict=verdict,
        match=match,
        payload=payload,
    )

    reason_codes = unique_codes(
        [
            *signals.reason_codes,
            *classification_reasons,
            *case_reasons,
            *match.reason_codes,
            *verdict_reasons,
            f"route_{department.value}",
            f"severity_{severity.value}",
            "human_review_required" if human_review_required else "human_review_optional",
        ]
    )

    confidence = calculate_confidence(
        case_type=case_type,
        match=match,
        verdict=verdict,
        reason_codes=reason_codes,
    )

    relevant_transaction_id = (
        match.transaction.transaction_id if match.transaction is not None else None
    )

    return AnalysisResponse(
        ticket_id=payload.ticket_id,
        relevant_transaction_id=relevant_transaction_id,
        evidence_verdict=verdict,
        case_type=case_type,
        severity=severity,
        department=department,
        agent_summary=build_agent_summary(
            case_type=case_type,
            verdict=verdict,
            match=match,
            transaction_count=len(transactions),
        ),
        recommended_next_action=build_next_action(
            case_type=case_type,
            verdict=verdict,
            match=match.transaction,
            department=department,
        ),
        customer_reply=build_customer_reply(
            case_type=case_type,
            verdict=verdict,
            match=match.transaction,
        ),
        human_review_required=human_review_required,
        confidence=confidence,
        reason_codes=reason_codes,
    )


def normalize(text: str) -> str:
    translated = text.translate(BANGLA_DIGITS)
    return re.sub(r"\s+", " ", translated.casefold()).strip()


def extract_complaint_signals(raw_complaint: str) -> ComplaintSignals:
    text = normalize(raw_complaint)
    case_scores: dict[CaseType, float] = {}
    reason_codes: list[str] = []

    for case_type, keywords in CASE_KEYWORDS.items():
        hits = [keyword for keyword in keywords if keyword in text]
        if hits:
            case_scores[case_type] = float(len(hits))
            reason_codes.append(f"complaint_signal_{case_type.value}")

    status_words = extract_status_words(text)
    risk_words = extract_risk_words(text)
    if risk_words:
        reason_codes.append("security_risk_language")

    return ComplaintSignals(
        text=text,
        case_scores=case_scores,
        amounts=extract_amounts(text),
        transaction_ids=extract_transaction_id_candidates(text),
        counterparties=extract_counterparty_candidates(text),
        time_hints=extract_time_hints(text),
        status_words=status_words,
        risk_words=risk_words,
        reason_codes=reason_codes,
    )


def classify_case(
    signals: ComplaintSignals,
    payload: AnalyzeTicketRequest,
    transactions: list[Transaction],
) -> tuple[CaseType, list[str]]:
    scores = dict(signals.case_scores)
    reasons: list[str] = []

    if (
        not scores
        and payload.user_type not in {UserType.merchant, UserType.agent}
        and not signals.status_words
    ):
        return CaseType.other, ["case_other"]

    evidence_scores, evidence_reasons = evidence_case_scores(transactions, payload)
    for case_type, score in evidence_scores.items():
        scores[case_type] = scores.get(case_type, 0.0) + score
    reasons.extend(evidence_reasons)

    if payload.user_type == UserType.merchant:
        scores[CaseType.merchant_settlement_delay] = (
            scores.get(CaseType.merchant_settlement_delay, 0.0) + 1.5
        )
        reasons.append("user_type_merchant_signal")
    elif payload.user_type == UserType.agent:
        scores[CaseType.agent_cash_in_issue] = (
            scores.get(CaseType.agent_cash_in_issue, 0.0) + 1.5
        )
        reasons.append("user_type_agent_signal")

    if not scores:
        return CaseType.other, ["case_other"]

    if CaseType.phishing_or_social_engineering in signals.case_scores:
        return CaseType.phishing_or_social_engineering, [
            "case_phishing_or_social_engineering"
        ]

    case_type = max(
        CASE_PRIORITY,
        key=lambda item: (scores.get(item, 0.0), -CASE_PRIORITY.index(item)),
    )
    if scores.get(case_type, 0.0) <= 0:
        case_type = CaseType.other

    return case_type, [f"case_{case_type.value}", *reasons]


def evidence_case_scores(
    transactions: list[Transaction], payload: AnalyzeTicketRequest
) -> tuple[dict[CaseType, float], list[str]]:
    scores: dict[CaseType, float] = {}
    reasons: list[str] = []

    if duplicate_groups(transactions):
        scores[CaseType.duplicate_payment] = scores.get(CaseType.duplicate_payment, 0) + 2.5
        reasons.append("evidence_duplicate_payment_pattern")

    if any(t.type == TransactionType.settlement for t in transactions):
        scores[CaseType.merchant_settlement_delay] = (
            scores.get(CaseType.merchant_settlement_delay, 0) + 1.0
        )
        reasons.append("evidence_settlement_transaction")

    if any(t.type == TransactionType.cash_in for t in transactions):
        scores[CaseType.agent_cash_in_issue] = (
            scores.get(CaseType.agent_cash_in_issue, 0) + 1.0
        )
        reasons.append("evidence_cash_in_transaction")

    if any(
        t.type in {TransactionType.payment, TransactionType.transfer}
        and t.status in {TransactionStatus.failed, TransactionStatus.pending}
        for t in transactions
    ):
        scores[CaseType.payment_failed] = scores.get(CaseType.payment_failed, 0) + 1.0
        reasons.append("evidence_failed_or_pending_payment")

    if any(t.type == TransactionType.refund for t in transactions):
        scores[CaseType.refund_request] = scores.get(CaseType.refund_request, 0) + 0.75
        reasons.append("evidence_refund_transaction")

    if payload.user_type == UserType.merchant:
        scores[CaseType.merchant_settlement_delay] = (
            scores.get(CaseType.merchant_settlement_delay, 0) + 0.75
        )
    elif payload.user_type == UserType.agent:
        scores[CaseType.agent_cash_in_issue] = scores.get(CaseType.agent_cash_in_issue, 0) + 0.75

    return scores, reasons


def refine_case_type(
    case_type: CaseType,
    signals: ComplaintSignals,
    match: TransactionMatch,
    payload: AnalyzeTicketRequest,
    transactions: list[Transaction],
) -> tuple[CaseType, list[str]]:
    reasons: list[str] = []

    if case_type == CaseType.phishing_or_social_engineering:
        return case_type, reasons

    if CaseType.refund_request in signals.case_scores:
        if (
            "deducted" in signals.status_words
            and match.transaction is not None
            and match.transaction.type in {TransactionType.payment, TransactionType.transfer}
            and match.transaction.status in {TransactionStatus.failed, TransactionStatus.pending}
        ):
            return CaseType.payment_failed, ["refund_language_attached_to_failed_payment"]
        if CaseType.payment_failed in signals.case_scores:
            return CaseType.payment_failed, ["refund_language_attached_to_failed_payment"]
        if CaseType.wrong_transfer in signals.case_scores:
            return CaseType.wrong_transfer, ["refund_language_attached_to_wrong_transfer"]
        if CaseType.duplicate_payment in signals.case_scores:
            return CaseType.duplicate_payment, ["refund_language_attached_to_duplicate"]
        return CaseType.refund_request, ["refund_request_preserved"]

    if payload.user_type == UserType.merchant and any(
        t.type == TransactionType.settlement for t in transactions
    ):
        return CaseType.merchant_settlement_delay, ["merchant_evidence_refined_case"]

    if payload.user_type == UserType.agent and any(
        t.type == TransactionType.cash_in for t in transactions
    ):
        return CaseType.agent_cash_in_issue, ["agent_evidence_refined_case"]

    if match.transaction is None:
        return case_type, reasons

    transaction = match.transaction
    if case_type == CaseType.other:
        if transaction.type == TransactionType.settlement:
            return CaseType.merchant_settlement_delay, ["transaction_type_refined_case"]
        if transaction.type == TransactionType.cash_in:
            return CaseType.agent_cash_in_issue, ["transaction_type_refined_case"]
        if transaction.type == TransactionType.payment and transaction.status in {
            TransactionStatus.failed,
            TransactionStatus.pending,
        }:
            return CaseType.payment_failed, ["transaction_status_refined_case"]

    return case_type, reasons


def find_relevant_transaction(
    signals: ComplaintSignals,
    case_type: CaseType,
    transactions: list[Transaction],
) -> TransactionMatch:
    if not transactions or case_type == CaseType.phishing_or_social_engineering:
        return TransactionMatch(None, 0.0, ["no_transaction_match"])

    scored: list[tuple[float, Transaction, list[str], bool]] = []
    expected_types = TRANSACTION_TYPES_BY_CASE.get(case_type, set())

    for transaction in transactions:
        score, reasons, conflicting = score_transaction(transaction, signals, case_type)

        if expected_types and transaction.type in expected_types:
            score += 2.0
            reasons.append("transaction_type_match")
        elif expected_types:
            score -= 1.0
            conflicting = True
            reasons.append("transaction_type_conflict")

        if duplicate_payment_present(transaction, transactions):
            score += 3.0
            reasons.append("duplicate_pattern_match")

        if score > 0:
            scored.append((score, transaction, unique_codes(reasons), conflicting))

    if not scored:
        return TransactionMatch(None, 0.0, ["no_transaction_match"])

    scored.sort(
        key=lambda item: (
            item[0],
            transaction_sort_timestamp(item[1]),
        ),
        reverse=True,
    )
    best_score, best_transaction, reasons, conflicting = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0

    threshold = matching_threshold(case_type, signals, transactions)
    if best_score < threshold:
        return TransactionMatch(None, best_score, ["no_transaction_match"])

    if len(scored) > 1 and best_score - second_score < AMBIGUITY_GAP:
        duplicate_pair_is_clear = (
            case_type == CaseType.duplicate_payment
            and "duplicate_pattern_match" in reasons
        )
        if "transaction_id_match" not in reasons and not duplicate_pair_is_clear:
            return TransactionMatch(
                None,
                best_score,
                ["ambiguous_transaction_match"],
                ambiguous=True,
            )

    if conflicting and not has_concrete_match_signal(reasons):
        return TransactionMatch(None, best_score, ["conflicting_weak_transaction_match"])

    if not has_concrete_match_signal(reasons) and not has_unique_evidence_match(
        best_transaction, case_type, transactions
    ):
        return TransactionMatch(None, best_score, ["no_concrete_transaction_signal"])

    if conflicting:
        reasons.append("conflicting_transaction_evidence")

    return TransactionMatch(best_transaction, best_score, unique_codes(reasons), conflicting=conflicting)


def score_transaction(
    transaction: Transaction, signals: ComplaintSignals, case_type: CaseType
) -> tuple[float, list[str], bool]:
    score = 0.0
    reasons: list[str] = []
    conflicting = False

    if transaction.transaction_id.casefold() in signals.transaction_ids:
        score += 10.0
        reasons.append("transaction_id_match")

    if signals.amounts:
        if any(amount_matches(transaction.amount, amount) for amount in signals.amounts):
            score += 3.0
            reasons.append("amount_match")
        elif has_money_language(signals.text):
            conflicting = True
            reasons.append("amount_conflict")

    counterparty_score = best_counterparty_score(transaction.counterparty, signals.counterparties)
    if counterparty_score >= 0.97:
        score += 4.0
        reasons.append("counterparty_match")
    elif counterparty_score >= 0.78:
        score += 2.0
        reasons.append("counterparty_partial_match")
    elif signals.counterparties:
        conflicting = True
        reasons.append("counterparty_conflict")

    time_score = best_time_score(transaction, signals.time_hints)
    if time_score > 0:
        score += time_score
        reasons.append("timestamp_clue_match")

    status_score, status_conflict, status_reason = status_score_for_case(
        transaction.status, case_type, signals
    )
    if status_score:
        score += status_score
        reasons.append(status_reason)
    if status_conflict:
        conflicting = True
        reasons.append(status_reason)

    return score, reasons, conflicting


def matching_threshold(
    case_type: CaseType, signals: ComplaintSignals, transactions: list[Transaction]
) -> float:
    if signals.transaction_ids:
        return 4.0
    if len(transactions) == 1 and case_type != CaseType.other:
        return 3.0
    if case_type == CaseType.other:
        return 5.0
    if case_type == CaseType.refund_request:
        return 4.0
    return 4.5


def has_concrete_match_signal(reasons: list[str]) -> bool:
    concrete = {
        "transaction_id_match",
        "amount_match",
        "counterparty_match",
        "counterparty_partial_match",
        "timestamp_clue_match",
        "duplicate_pattern_match",
    }
    return bool(concrete.intersection(reasons))


def has_unique_evidence_match(
    transaction: Transaction, case_type: CaseType, transactions: list[Transaction]
) -> bool:
    expected_types = TRANSACTION_TYPES_BY_CASE.get(case_type, set())
    if not expected_types:
        return False

    compatible = [item for item in transactions if item.type in expected_types]
    return len(compatible) == 1 and compatible[0].transaction_id == transaction.transaction_id


def determine_verdict(
    case_type: CaseType,
    signals: ComplaintSignals,
    match: TransactionMatch,
    transactions: list[Transaction],
) -> tuple[EvidenceVerdict, list[str]]:
    transaction = match.transaction

    if case_type == CaseType.phishing_or_social_engineering:
        return EvidenceVerdict.insufficient_data, ["security_case_not_transaction_proven"]

    if match.ambiguous:
        return EvidenceVerdict.insufficient_data, ["ambiguous_evidence"]

    if transaction is None:
        if not transactions:
            return EvidenceVerdict.insufficient_data, ["empty_transaction_history"]
        return EvidenceVerdict.insufficient_data, ["no_matching_transaction_in_history"]

    if case_type == CaseType.wrong_transfer:
        if transaction.type != TransactionType.transfer:
            return EvidenceVerdict.inconsistent, ["matched_transaction_not_transfer"]
        if repeated_completed_transfer_to_same_counterparty(transaction, transactions):
            return EvidenceVerdict.inconsistent, ["recipient_has_prior_transfer_history"]
        if transaction.status == TransactionStatus.completed:
            return EvidenceVerdict.consistent, ["completed_transfer_supports_claim"]
        if transaction.status in {TransactionStatus.failed, TransactionStatus.reversed}:
            return EvidenceVerdict.inconsistent, ["transfer_not_completed"]
        return EvidenceVerdict.insufficient_data, ["transfer_still_pending"]

    if case_type == CaseType.payment_failed:
        if transaction.type not in {TransactionType.payment, TransactionType.transfer}:
            return EvidenceVerdict.inconsistent, ["matched_transaction_not_payment_like"]
        if transaction.status in {TransactionStatus.failed, TransactionStatus.pending}:
            return EvidenceVerdict.consistent, ["failed_or_pending_payment_found"]
        if transaction.status in {TransactionStatus.completed, TransactionStatus.reversed}:
            return EvidenceVerdict.inconsistent, ["payment_status_contradicts_failed_claim"]

    if case_type == CaseType.duplicate_payment:
        if duplicate_payment_present(transaction, transactions):
            return EvidenceVerdict.consistent, ["duplicate_completed_payments_found"]
        if transaction.type == TransactionType.payment:
            return EvidenceVerdict.inconsistent, ["no_duplicate_payment_in_history"]
        return EvidenceVerdict.insufficient_data, ["duplicate_claim_not_proven"]

    if case_type == CaseType.refund_request:
        return refund_verdict(transaction, signals, transactions)

    if case_type == CaseType.merchant_settlement_delay:
        if transaction.type != TransactionType.settlement:
            return EvidenceVerdict.inconsistent, ["matched_transaction_not_settlement"]
        if transaction.status in {TransactionStatus.pending, TransactionStatus.failed}:
            return EvidenceVerdict.consistent, ["settlement_not_completed"]
        if transaction.status == TransactionStatus.completed:
            return EvidenceVerdict.inconsistent, ["settlement_already_completed"]
        return EvidenceVerdict.insufficient_data, ["settlement_status_unclear"]

    if case_type == CaseType.agent_cash_in_issue:
        if transaction.type != TransactionType.cash_in:
            return EvidenceVerdict.inconsistent, ["matched_transaction_not_cash_in"]
        if transaction.status in {TransactionStatus.pending, TransactionStatus.failed}:
            return EvidenceVerdict.consistent, ["cash_in_not_reflected_in_history"]
        if transaction.status == TransactionStatus.completed:
            return EvidenceVerdict.inconsistent, ["cash_in_completed_in_history"]
        return EvidenceVerdict.insufficient_data, ["cash_in_status_unclear"]

    return EvidenceVerdict.insufficient_data, ["case_needs_manual_context"]


def refund_verdict(
    transaction: Transaction, signals: ComplaintSignals, transactions: list[Transaction]
) -> tuple[EvidenceVerdict, list[str]]:
    if transaction.type == TransactionType.refund:
        if transaction.status == TransactionStatus.completed:
            if "not_received" in signals.status_words:
                return EvidenceVerdict.inconsistent, ["refund_already_completed"]
            return EvidenceVerdict.consistent, ["refund_transaction_completed"]
        if transaction.status in {TransactionStatus.pending, TransactionStatus.failed}:
            return EvidenceVerdict.consistent, ["refund_not_completed"]
        return EvidenceVerdict.inconsistent, ["refund_transaction_reversed"]

    related_refund = find_related_refund(transaction, transactions)
    if related_refund and related_refund.status == TransactionStatus.completed:
        if "not_received" in signals.status_words:
            return EvidenceVerdict.inconsistent, ["related_refund_already_completed"]
        return EvidenceVerdict.consistent, ["related_refund_found"]

    if transaction.status in {
        TransactionStatus.failed,
        TransactionStatus.pending,
        TransactionStatus.reversed,
    }:
        return EvidenceVerdict.consistent, ["refund_review_supported_by_status"]

    if transaction.status == TransactionStatus.completed and transaction.type in {
        TransactionType.payment,
        TransactionType.transfer,
        TransactionType.cash_in,
        TransactionType.cash_out,
    }:
        return EvidenceVerdict.consistent, ["original_transaction_found_for_refund_review"]

    return EvidenceVerdict.insufficient_data, ["refund_eligibility_requires_review"]


def determine_severity(
    case_type: CaseType,
    transaction: Transaction | None,
    verdict: EvidenceVerdict,
    signals: ComplaintSignals,
    match: TransactionMatch,
) -> Severity:
    amount = transaction.amount if transaction is not None else 0.0

    if case_type == CaseType.phishing_or_social_engineering or signals.risk_words:
        return Severity.critical
    if case_type == CaseType.other:
        return Severity.low
    if amount >= CRITICAL_VALUE_AMOUNT:
        return Severity.critical
    if amount >= HIGH_VALUE_AMOUNT and case_type != CaseType.merchant_settlement_delay:
        return Severity.high
    if case_type == CaseType.wrong_transfer:
        if verdict == EvidenceVerdict.consistent:
            return Severity.high
        return Severity.medium
    if case_type == CaseType.payment_failed and "deducted" in signals.status_words:
        return Severity.high
    if case_type == CaseType.duplicate_payment:
        return Severity.high
    if case_type == CaseType.agent_cash_in_issue and verdict == EvidenceVerdict.consistent:
        return Severity.high
    if case_type == CaseType.refund_request and verdict == EvidenceVerdict.consistent:
        return Severity.low
    if case_type == CaseType.refund_request and verdict in {
        EvidenceVerdict.inconsistent,
        EvidenceVerdict.insufficient_data,
    }:
        return Severity.high
    if match.conflicting:
        return Severity.high
    if case_type in {
        CaseType.payment_failed,
        CaseType.merchant_settlement_delay,
        CaseType.agent_cash_in_issue,
        CaseType.refund_request,
    }:
        return Severity.medium
    if verdict == EvidenceVerdict.insufficient_data:
        return Severity.medium
    return Severity.low


def determine_department(
    case_type: CaseType,
    payload: AnalyzeTicketRequest,
    severity: Severity,
    verdict: EvidenceVerdict,
    match: TransactionMatch,
) -> Department:
    if case_type == CaseType.refund_request:
        if severity in {Severity.high, Severity.critical} or verdict != EvidenceVerdict.consistent:
            return Department.dispute_resolution
        return Department.customer_support

    if payload.user_type == UserType.merchant and case_type != CaseType.phishing_or_social_engineering:
        return Department.merchant_operations
    if payload.user_type == UserType.agent and case_type != CaseType.phishing_or_social_engineering:
        return Department.agent_operations

    return DEPARTMENT_BY_CASE[case_type]


def should_require_human_review(
    case_type: CaseType,
    severity: Severity,
    verdict: EvidenceVerdict,
    match: TransactionMatch,
    payload: AnalyzeTicketRequest,
) -> bool:
    if case_type in {
        CaseType.phishing_or_social_engineering,
        CaseType.agent_cash_in_issue,
    }:
        return True
    if case_type == CaseType.wrong_transfer:
        return match.transaction is not None and not match.ambiguous
    if case_type == CaseType.duplicate_payment:
        return True
    if (
        case_type == CaseType.payment_failed
        and verdict == EvidenceVerdict.consistent
        and match.transaction is not None
        and match.transaction.amount < HIGH_VALUE_AMOUNT
    ):
        return False
    if case_type == CaseType.refund_request and verdict != EvidenceVerdict.consistent:
        return True
    if severity in {Severity.high, Severity.critical}:
        return True
    if verdict == EvidenceVerdict.insufficient_data:
        return case_type not in {CaseType.other, CaseType.wrong_transfer}
    if match.ambiguous or match.conflicting:
        return case_type not in {CaseType.wrong_transfer}
    if payload.user_type in {UserType.merchant, UserType.agent}:
        return verdict != EvidenceVerdict.consistent
    return False


def build_agent_summary(
    case_type: CaseType,
    verdict: EvidenceVerdict,
    match: TransactionMatch,
    transaction_count: int,
) -> str:
    label = readable_case(case_type)
    if match.ambiguous:
        return (
            f"Ticket appears to be {label}, but multiple transactions could match; "
            "evidence is insufficient for a single transaction decision."
        )
    if match.transaction is None:
        return (
            f"Ticket appears to be {label}, but no provided transaction clearly matches "
            f"from {transaction_count} history entries."
        )

    transaction = match.transaction
    return (
        f"Ticket appears to be {label} linked to {transaction.transaction_id} "
        f"({transaction.type.value}, {transaction.amount:g} BDT, {transaction.status.value}); "
        f"evidence is {verdict.value}."
    )


def build_next_action(
    case_type: CaseType,
    verdict: EvidenceVerdict,
    match: Transaction | None,
    department: Department,
) -> str:
    txn_ref = f" {match.transaction_id}" if match is not None else ""

    if case_type == CaseType.phishing_or_social_engineering:
        return (
            "Escalate to fraud_risk, preserve the complaint details, and direct the "
            "customer only to official support channels."
        )

    if verdict == EvidenceVerdict.insufficient_data:
        return (
            f"Route to {department.value} for manual review and request only non-sensitive "
            "clarifying details such as date, amount, and counterparty."
        )

    if verdict == EvidenceVerdict.inconsistent:
        return (
            f"Route to {department.value} to review transaction{txn_ref} and explain the "
            "official record without promising financial action."
        )

    if case_type == CaseType.wrong_transfer:
        return (
            f"Route transaction{txn_ref} to dispute_resolution for ownership checks and "
            "standard wrong-transfer review."
        )

    if case_type == CaseType.payment_failed:
        return (
            f"Ask payments_ops to verify transaction{txn_ref} status and ledger impact "
            "before any eligible case handling."
        )

    if case_type == CaseType.duplicate_payment:
        return (
            f"Ask payments_ops to compare duplicate payment evidence around transaction{txn_ref} "
            "before any eligible case handling."
        )

    if case_type == CaseType.refund_request:
        return (
            f"Route transaction{txn_ref} to {department.value} for eligibility review "
            "through official channels."
        )

    if case_type == CaseType.merchant_settlement_delay:
        return (
            f"Route transaction{txn_ref} to merchant_operations to check settlement status "
            "and the expected processing window."
        )

    if case_type == CaseType.agent_cash_in_issue:
        return (
            f"Route transaction{txn_ref} to agent_operations to verify agent cash-in status "
            "and balance posting."
        )

    return "Handle through customer_support using the available complaint and history."


def build_customer_reply(
    case_type: CaseType,
    verdict: EvidenceVerdict,
    match: Transaction | None,
) -> str:
    txn_text = f" for transaction {match.transaction_id}" if match is not None else ""

    if case_type == CaseType.phishing_or_social_engineering:
        return (
            "We have noted your security concern. Do not share confidential credentials "
            "with anyone, and continue only through official support channels while our "
            "team reviews the report."
        )

    if verdict == EvidenceVerdict.inconsistent:
        return (
            f"We have reviewed the available transaction history{txn_text}, and it does "
            "not currently support the reported issue. Our team will recheck the details "
            "through official records."
        )

    if verdict == EvidenceVerdict.insufficient_data:
        return (
            "We have noted your concern, but the provided transaction history is not enough "
            "to confirm the issue. Our team will review it through official channels and "
            "may ask for non-sensitive details such as date, amount, or recipient."
        )

    return (
        f"We have noted your concern{txn_text}. The available transaction history supports "
        "that this needs follow-up. Eligible cases will be reviewed through official "
        "channels after verification."
    )


def calculate_confidence(
    case_type: CaseType,
    match: TransactionMatch,
    verdict: EvidenceVerdict,
    reason_codes: list[str],
) -> float:
    confidence = 0.25

    if case_type != CaseType.other:
        confidence += 0.12
    if match.transaction is not None:
        confidence += min(match.score / 25.0, 0.35)
    if "transaction_id_match" in reason_codes:
        confidence += 0.16
    if "amount_match" in reason_codes:
        confidence += 0.08
    if "counterparty_match" in reason_codes:
        confidence += 0.08
    if verdict == EvidenceVerdict.consistent:
        confidence += 0.08
    elif verdict == EvidenceVerdict.inconsistent:
        confidence += 0.04
    else:
        confidence -= 0.12
    if match.ambiguous:
        confidence -= 0.18
    if match.conflicting:
        confidence -= 0.10
    if "empty_transaction_history" in reason_codes or "no_matching_transaction_in_history" in reason_codes:
        confidence -= 0.12

    return round(max(0.0, min(confidence, 0.98)), 2)


def extract_amounts(text: str) -> list[float]:
    amounts: list[float] = []
    amount_pattern = (
        r"(?<![\w+.,-])(?:bdt|tk|taka|৳)?\s*"
        r"((?:\d{1,3}(?:,\d{3})+|\d{2,9})(?:\.\d+)?)(?![\w-])"
    )
    for match in re.finditer(amount_pattern, text):
        raw = match.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        if value > 0:
            amounts.append(value)
    return unique_numbers(amounts)


def extract_transaction_id_candidates(text: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in re.finditer(
            r"\b(?:txn|tx|tr|trx)[-_]?[a-z0-9]+(?:[-_][a-z0-9]+)*\b",
            text,
            re.IGNORECASE,
        )
    }


def extract_counterparty_candidates(text: str) -> set[str]:
    candidates: set[str] = set()

    for match in re.finditer(r"(?:\+?88)?01[3-9]\d{8}\b", text):
        candidates.add(only_digits(match.group(0))[-11:])

    for match in re.finditer(
        r"\b(?:m|merchant|agent|ag)[-_][a-z0-9]+(?:[-_][a-z0-9]+)*\b",
        text,
        re.IGNORECASE,
    ):
        candidates.add(match.group(0).casefold())

    for match in re.finditer(
        r"\b(?:merchant|agent)\s+([a-z]{0,4}[-_]\d+[a-z0-9-_]*)\b",
        text,
        re.IGNORECASE,
    ):
        candidates.add(match.group(1).casefold())

    return candidates


def extract_time_hints(text: str) -> list[TimeHint]:
    hints: list[TimeHint] = []

    for match in re.finditer(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", text):
        hints.append(TimeHint(hour=int(match.group(1)), minute=int(match.group(2))))

    for match in re.finditer(r"\b(1[0-2]|0?[1-9])\s*(am|pm)\b", text):
        hour = int(match.group(1)) % 12
        if match.group(2) == "pm":
            hour += 12
        hints.append(TimeHint(hour=hour))

    for match in re.finditer(r"\b([01]?\d|2[0-3])\s*(?:ta|টার|টায়|টায়|টা)\b", text):
        hints.append(TimeHint(hour=int(match.group(1))))

    return unique_time_hints(hints)


def extract_status_words(text: str) -> set[str]:
    words: set[str] = set()
    if any(token in text for token in ("failed", "fail", "ফেইল", "ফেল", "kete geche")):
        words.add("failed")
    if any(token in text for token in ("pending", "processing", "hold", "পেন্ডিং")):
        words.add("pending")
    if any(token in text for token in ("completed", "successful", "success", "সফল")):
        words.add("completed")
    if any(token in text for token in ("deducted", "kete", "কেটে", "kata", "balance deducted")):
        words.add("deducted")
    if any(token in text for token in ("not received", "did not receive", "paini", "aseni", "আসেনি", "পাইনি")):
        words.add("not_received")
    return words


def extract_risk_words(text: str) -> set[str]:
    risk_tokens = {
        "otp",
        "pin",
        "password",
        "credential",
        "scam",
        "fraud",
        "phishing",
        "hack",
        "ওটিপি",
        "পিন",
        "পাসওয়ার্ড",
        "পাসওয়ার্ড",
        "প্রতারণা",
        "স্ক্যাম",
    }
    return {token for token in risk_tokens if token in text}


def status_score_for_case(
    status: TransactionStatus, case_type: CaseType, signals: ComplaintSignals
) -> tuple[float, bool, str]:
    if case_type == CaseType.wrong_transfer:
        if status == TransactionStatus.completed:
            return 1.5, False, "status_supports_claim"
        if status in {TransactionStatus.failed, TransactionStatus.reversed}:
            return 1.0, True, "status_conflicts_with_claim"

    if case_type == CaseType.payment_failed:
        if status in {TransactionStatus.failed, TransactionStatus.pending}:
            return 2.0, False, "status_supports_claim"
        if status in {TransactionStatus.completed, TransactionStatus.reversed}:
            return 1.0, True, "status_conflicts_with_claim"

    if case_type == CaseType.duplicate_payment:
        if status == TransactionStatus.completed:
            return 1.0, False, "status_supports_claim"

    if case_type == CaseType.refund_request:
        if status in {TransactionStatus.failed, TransactionStatus.pending, TransactionStatus.reversed}:
            return 1.5, False, "status_supports_review"
        if status == TransactionStatus.completed and "not_received" in signals.status_words:
            return 1.0, True, "status_conflicts_with_claim"

    if case_type == CaseType.merchant_settlement_delay:
        if status in {TransactionStatus.pending, TransactionStatus.failed}:
            return 2.0, False, "status_supports_claim"
        if status == TransactionStatus.completed:
            return 1.0, True, "status_conflicts_with_claim"

    if case_type == CaseType.agent_cash_in_issue:
        if status in {TransactionStatus.pending, TransactionStatus.failed}:
            return 2.0, False, "status_supports_claim"
        if status == TransactionStatus.completed:
            return 1.0, True, "status_conflicts_with_claim"

    return 0.0, False, "status_not_used"


def best_counterparty_score(counterparty: str, candidates: set[str]) -> float:
    if not candidates:
        return 0.0

    normalized_counterparty = normalize_counterparty(counterparty)
    counterparty_digits = only_digits(normalized_counterparty)
    scores: list[float] = []
    for candidate in candidates:
        normalized_candidate = normalize_counterparty(candidate)
        candidate_digits = only_digits(normalized_candidate)
        if counterparty_digits and candidate_digits:
            scores.append(1.0 if normalized_counterparty == normalized_candidate else 0.0)
        else:
            scores.append(
                SequenceMatcher(None, normalized_counterparty, normalized_candidate).ratio()
            )
    return max(scores)


def best_time_score(transaction: Transaction, hints: list[TimeHint]) -> float:
    if not hints:
        return 0.0

    timestamp = parse_timestamp(transaction.timestamp)
    if timestamp is None:
        return 0.0

    best = 0.0
    for hint in hints:
        hour_delta = min(
            abs(timestamp.hour - hint.hour),
            24 - abs(timestamp.hour - hint.hour),
        )
        if hour_delta == 0:
            if hint.minute is not None and abs(timestamp.minute - hint.minute) > 20:
                best = max(best, 1.0)
            else:
                best = max(best, 2.0)
        elif hour_delta == 1:
            best = max(best, 1.0)
    return best


def parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def duplicate_payment_present(transaction: Transaction, transactions: list[Transaction]) -> bool:
    if transaction.type != TransactionType.payment or transaction.status != TransactionStatus.completed:
        return False

    for other in transactions:
        if other.transaction_id == transaction.transaction_id:
            continue
        if (
            other.type == TransactionType.payment
            and other.status == TransactionStatus.completed
            and amount_matches(other.amount, transaction.amount)
            and normalize_counterparty(other.counterparty)
            == normalize_counterparty(transaction.counterparty)
        ):
            return True
    return False


def repeated_completed_transfer_to_same_counterparty(
    transaction: Transaction, transactions: list[Transaction]
) -> bool:
    if transaction.type != TransactionType.transfer or transaction.status != TransactionStatus.completed:
        return False

    counterparty = normalize_counterparty(transaction.counterparty)
    for other in transactions:
        if other.transaction_id == transaction.transaction_id:
            continue
        if (
            other.type == TransactionType.transfer
            and other.status == TransactionStatus.completed
            and normalize_counterparty(other.counterparty) == counterparty
        ):
            return True
    return False


def duplicate_groups(transactions: list[Transaction]) -> list[list[Transaction]]:
    groups: dict[tuple[float, str], list[Transaction]] = {}
    for transaction in transactions:
        if transaction.type != TransactionType.payment or transaction.status != TransactionStatus.completed:
            continue
        key = (round(transaction.amount, 2), normalize_counterparty(transaction.counterparty))
        groups.setdefault(key, []).append(transaction)
    return [items for items in groups.values() if len(items) > 1]


def transaction_sort_timestamp(transaction: Transaction) -> float:
    parsed = parse_timestamp(transaction.timestamp)
    if parsed is None:
        return 0.0
    return parsed.timestamp()


def find_related_refund(
    transaction: Transaction, transactions: list[Transaction]
) -> Transaction | None:
    for other in transactions:
        if other.type != TransactionType.refund:
            continue
        if amount_matches(other.amount, transaction.amount) and (
            normalize_counterparty(other.counterparty)
            == normalize_counterparty(transaction.counterparty)
        ):
            return other
    return None


def amount_matches(left: float, right: float) -> bool:
    return isclose(left, right, rel_tol=0.0, abs_tol=max(1.0, left * 0.001))


def has_money_language(text: str) -> bool:
    return any(token in text for token in ("taka", "tk", "bdt", "৳", "টাকা"))


def normalize_counterparty(value: str) -> str:
    normalized = normalize(value)
    digits = only_digits(normalized)
    if digits and len(digits) >= 8:
        return digits[-11:]
    return re.sub(r"\s+", "", normalized)


def readable_case(case_type: CaseType) -> str:
    return case_type.value.replace("_", " ")


def unique_codes(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for code in codes:
        normalized = code.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def unique_numbers(values: list[float]) -> list[float]:
    unique: list[float] = []
    for value in values:
        if not any(amount_matches(value, existing) for existing in unique):
            unique.append(value)
    return unique


def unique_time_hints(values: list[TimeHint]) -> list[TimeHint]:
    seen: set[tuple[int, int | None]] = set()
    unique: list[TimeHint] = []
    for value in values:
        key = (value.hour, value.minute)
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value)
