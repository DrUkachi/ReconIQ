-- BankRecon initial schema. Generated from app/models, then checked in.
-- Regenerate with: python scripts/generate_ddl.py

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE idempotency_record (
	key VARCHAR(255) NOT NULL,
	endpoint VARCHAR(128) NOT NULL,
	response_status INTEGER NOT NULL,
	response_body JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_idempotency_record PRIMARY KEY (key, endpoint)
);

CREATE TABLE processed_event (
	slack_event_id VARCHAR(64) NOT NULL,
	event_type VARCHAR(48) NOT NULL,
	received_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_processed_event PRIMARY KEY (slack_event_id)
);

CREATE TABLE processed_interaction (
	trigger_id VARCHAR(128) NOT NULL,
	received_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_processed_interaction PRIMARY KEY (trigger_id)
);

CREATE TABLE workspace (
	id UUID NOT NULL,
	slack_team_id VARCHAR(32) NOT NULL,
	name VARCHAR(255) NOT NULL,
	bot_token TEXT,
	bot_user_id VARCHAR(32),
	slack_retry_at TIMESTAMP WITH TIME ZONE,
	recon_channel_id VARCHAR(32),
	approval_value_threshold_minor BIGINT NOT NULL,
	uninstalled_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_workspace PRIMARY KEY (id),
	CONSTRAINT uq_workspace_slack_team_id UNIQUE (slack_team_id)
);

CREATE TABLE app_user (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	slack_user_id VARCHAR(32) NOT NULL,
	display_name VARCHAR(255) NOT NULL,
	role VARCHAR(16) NOT NULL,
	email_masked VARCHAR(255),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_app_user PRIMARY KEY (id),
	CONSTRAINT uq_app_user_workspace_id UNIQUE (workspace_id, slack_user_id),
	CONSTRAINT fk_app_user_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);

CREATE TABLE conversation_evidence (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	channel_id VARCHAR(32) NOT NULL,
	ts VARCHAR(32) NOT NULL,
	thread_ts VARCHAR(32),
	author_slack_id VARCHAR(32) NOT NULL,
	posted_at TIMESTAMP WITH TIME ZONE NOT NULL,
	excerpt VARCHAR(200) NOT NULL,
	permalink TEXT,
	amounts_minor BIGINT[] NOT NULL,
	refs_norm TEXT[] NOT NULL,
	invoices TEXT[] NOT NULL,
	counterparties TEXT[] NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_conversation_evidence PRIMARY KEY (id),
	CONSTRAINT uniq_message UNIQUE (workspace_id, channel_id, ts),
	CONSTRAINT fk_conversation_evidence_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);
CREATE INDEX ix_evidence_amounts ON conversation_evidence USING gin (amounts_minor);
CREATE INDEX ix_evidence_invoices ON conversation_evidence USING gin (invoices);
CREATE INDEX ix_evidence_posted ON conversation_evidence (workspace_id, posted_at);
CREATE INDEX ix_evidence_refs ON conversation_evidence USING gin (refs_norm);

CREATE TABLE job (
	id UUID NOT NULL,
	workspace_id UUID,
	kind VARCHAR(48) NOT NULL,
	payload JSONB NOT NULL,
	idempotency_key VARCHAR(255) NOT NULL,
	state VARCHAR(16) NOT NULL,
	attempts INTEGER NOT NULL,
	leased_until TIMESTAMP WITH TIME ZONE,
	last_error TEXT,
	correlation_id VARCHAR(32),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_job PRIMARY KEY (id),
	CONSTRAINT uniq_idem UNIQUE (idempotency_key),
	CONSTRAINT fk_job_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE
);
CREATE INDEX ix_job_pending ON job (state, created_at) WHERE state = 'PENDING';

CREATE TABLE reconciliation (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	account_last4 VARCHAR(4) NOT NULL,
	period_start DATE NOT NULL,
	period_end DATE NOT NULL,
	currency VARCHAR(3) NOT NULL,
	state VARCHAR(24) NOT NULL,
	failure_code VARCHAR(48),
	slack_channel_id VARCHAR(32),
	created_by UUID,
	completed_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_reconciliation PRIMARY KEY (id),
	CONSTRAINT uniq_period UNIQUE (workspace_id, account_last4, period_start, period_end, currency),
	CONSTRAINT fk_reconciliation_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_reconciliation_created_by_app_user FOREIGN KEY(created_by) REFERENCES app_user (id)
);
CREATE INDEX ix_reconciliation_workspace_state ON reconciliation (workspace_id, state);

CREATE TABLE slack_intake (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	actor_user_id UUID NOT NULL,
	channel_id VARCHAR(32) NOT NULL,
	thread_ts VARCHAR(32) NOT NULL,
	account_last4 VARCHAR(4),
	period_start DATE,
	period_end DATE,
	status VARCHAR(16) NOT NULL,
	revision INTEGER NOT NULL,
	selected_files JSONB NOT NULL,
	reconciliation_ids JSONB NOT NULL,
	last_prompt VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_slack_intake PRIMARY KEY (id),
	CONSTRAINT one_intake_per_thread UNIQUE (workspace_id, channel_id, thread_ts),
	CONSTRAINT fk_slack_intake_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id),
	CONSTRAINT fk_slack_intake_actor_user_id_app_user FOREIGN KEY(actor_user_id) REFERENCES app_user (id)
);

CREATE TABLE workspace_claim (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	conversation_evidence_id UUID NOT NULL,
	claimed_amount_minor BIGINT,
	claimed_direction VARCHAR(8),
	claimed_reference VARCHAR(255),
	claimed_counterparty VARCHAR(255),
	claimed_date DATE,
	author_slack_id VARCHAR(32) NOT NULL,
	verified BOOLEAN NOT NULL,
	verified_by UUID,
	verified_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_workspace_claim PRIMARY KEY (id),
	CONSTRAINT fk_workspace_claim_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_workspace_claim_conversation_evidence_id_conversatio_0eb8 FOREIGN KEY(conversation_evidence_id) REFERENCES conversation_evidence (id) ON DELETE CASCADE,
	CONSTRAINT fk_workspace_claim_verified_by_app_user FOREIGN KEY(verified_by) REFERENCES app_user (id)
);
CREATE INDEX ix_claim_workspace_amount ON workspace_claim (workspace_id, claimed_amount_minor);

CREATE TABLE bank_transaction (
	id UUID NOT NULL,
	reconciliation_id UUID NOT NULL,
	row_index INTEGER NOT NULL,
	value_date DATE NOT NULL,
	narration TEXT NOT NULL,
	reference_raw VARCHAR(255) NOT NULL,
	reference_norm VARCHAR(255) NOT NULL,
	counterparty_norm VARCHAR(255) NOT NULL,
	amount_minor BIGINT NOT NULL,
	direction VARCHAR(8) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	balance_minor BIGINT,
	status VARCHAR(16) NOT NULL,
	warnings JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_bank_transaction PRIMARY KEY (id),
	CONSTRAINT ck_bank_transaction_amount_positive CHECK (amount_minor > 0),
	CONSTRAINT ck_bank_transaction_dir CHECK (direction IN ('CREDIT','DEBIT')),
	CONSTRAINT uq_bank_transaction_reconciliation_id UNIQUE (reconciliation_id, row_index),
	CONSTRAINT fk_bank_transaction_reconciliation_id_reconciliation FOREIGN KEY(reconciliation_id) REFERENCES reconciliation (id) ON DELETE CASCADE
);
CREATE INDEX ix_bank_transaction_counterparty_norm ON bank_transaction (counterparty_norm);
CREATE INDEX ix_bank_transaction_recon_amount_date ON bank_transaction (reconciliation_id, amount_minor, value_date);
CREATE INDEX ix_bank_transaction_recon_status ON bank_transaction (reconciliation_id, status);
CREATE INDEX ix_bank_transaction_reference_norm ON bank_transaction (reference_norm);

CREATE TABLE exception_case (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	reconciliation_id UUID NOT NULL,
	type VARCHAR(32) NOT NULL,
	state VARCHAR(16) NOT NULL,
	priority VARCHAR(16) NOT NULL,
	title VARCHAR(512) NOT NULL,
	summary TEXT NOT NULL,
	value_at_risk_minor BIGINT NOT NULL,
	currency VARCHAR(3) NOT NULL,
	assignee_id UUID,
	due_at TIMESTAMP WITH TIME ZONE,
	escalated_to UUID,
	escalated_at TIMESTAMP WITH TIME ZONE,
	slack_channel_id VARCHAR(32),
	slack_thread_ts VARCHAR(32),
	permalink TEXT,
	version INTEGER DEFAULT '0' NOT NULL,
	closed_at TIMESTAMP WITH TIME ZONE,
	reopened_reason TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_exception_case PRIMARY KEY (id),
	CONSTRAINT uniq_thread UNIQUE (slack_channel_id, slack_thread_ts),
	CONSTRAINT fk_exception_case_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_exception_case_reconciliation_id_reconciliation FOREIGN KEY(reconciliation_id) REFERENCES reconciliation (id) ON DELETE CASCADE,
	CONSTRAINT fk_exception_case_assignee_id_app_user FOREIGN KEY(assignee_id) REFERENCES app_user (id),
	CONSTRAINT fk_exception_case_escalated_to_app_user FOREIGN KEY(escalated_to) REFERENCES app_user (id)
);
CREATE INDEX ix_case_assignee_state ON exception_case (assignee_id, state);
CREATE INDEX ix_case_workspace_state ON exception_case (workspace_id, state);

CREATE TABLE payment_record (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	reconciliation_id UUID,
	external_id VARCHAR(128) NOT NULL,
	record_date DATE NOT NULL,
	amount_minor BIGINT NOT NULL,
	direction VARCHAR(8) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	reference_raw VARCHAR(255) NOT NULL,
	reference_norm VARCHAR(255) NOT NULL,
	counterparty_raw VARCHAR(255) NOT NULL,
	counterparty_norm VARCHAR(255) NOT NULL,
	status VARCHAR(16) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_payment_record PRIMARY KEY (id),
	CONSTRAINT ck_payment_record_amount_positive CHECK (amount_minor > 0),
	CONSTRAINT ck_payment_record_dir CHECK (direction IN ('CREDIT','DEBIT')),
	CONSTRAINT fk_payment_record_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_payment_record_reconciliation_id_reconciliation FOREIGN KEY(reconciliation_id) REFERENCES reconciliation (id) ON DELETE SET NULL
);
CREATE INDEX ix_payment_record_counterparty_norm ON payment_record (counterparty_norm);
CREATE INDEX ix_payment_record_open ON payment_record (workspace_id, amount_minor, record_date) WHERE status = 'OPEN';
CREATE INDEX ix_payment_record_reference_norm ON payment_record (reference_norm);

CREATE TABLE slack_intake_file (
	id UUID NOT NULL,
	intake_id UUID NOT NULL,
	slack_file_id VARCHAR(32) NOT NULL,
	filename VARCHAR(512) NOT NULL,
	role VARCHAR(16) NOT NULL,
	state VARCHAR(16) NOT NULL,
	content BYTEA,
	sha256 VARCHAR(64),
	report JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_slack_intake_file PRIMARY KEY (id),
	CONSTRAINT one_intake_file UNIQUE (intake_id, slack_file_id),
	CONSTRAINT fk_slack_intake_file_intake_id_slack_intake FOREIGN KEY(intake_id) REFERENCES slack_intake (id) ON DELETE CASCADE
);

CREATE TABLE source_import (
	id UUID NOT NULL,
	reconciliation_id UUID NOT NULL,
	kind VARCHAR(8) NOT NULL,
	filename VARCHAR(512) NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	byte_size INTEGER NOT NULL,
	raw_rows JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_source_import PRIMARY KEY (id),
	CONSTRAINT one_source_per_kind UNIQUE (reconciliation_id, kind),
	CONSTRAINT ck_source_import_source_kind CHECK (kind IN ('bank', 'ledger')),
	CONSTRAINT fk_source_import_reconciliation_id_reconciliation FOREIGN KEY(reconciliation_id) REFERENCES reconciliation (id) ON DELETE CASCADE
);

CREATE TABLE statement (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	reconciliation_id UUID NOT NULL,
	slack_file_id VARCHAR(32),
	filename VARCHAR(512) NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	byte_size INTEGER NOT NULL,
	page_count INTEGER NOT NULL,
	storage_path TEXT,
	extraction_method VARCHAR(16) NOT NULL,
	confidence INTEGER NOT NULL,
	inferred_date_format VARCHAR(32),
	balance_breaks INTEGER NOT NULL,
	skipped_rows INTEGER NOT NULL,
	warnings JSONB NOT NULL,
	raw_pages JSONB NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_statement PRIMARY KEY (id),
	CONSTRAINT one_per_recon UNIQUE (reconciliation_id),
	CONSTRAINT uniq_content UNIQUE (workspace_id, content_sha256, currency),
	CONSTRAINT fk_statement_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_statement_reconciliation_id_reconciliation FOREIGN KEY(reconciliation_id) REFERENCES reconciliation (id) ON DELETE CASCADE
);

CREATE TABLE audit_event (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	reconciliation_id UUID,
	case_id UUID,
	actor_user_id UUID,
	actor_slack_id VARCHAR(32),
	action VARCHAR(64) NOT NULL,
	from_state VARCHAR(32),
	to_state VARCHAR(32),
	reason TEXT,
	detail JSONB NOT NULL,
	correlation_id VARCHAR(32),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_audit_event PRIMARY KEY (id),
	CONSTRAINT fk_audit_event_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_audit_event_reconciliation_id_reconciliation FOREIGN KEY(reconciliation_id) REFERENCES reconciliation (id) ON DELETE SET NULL,
	CONSTRAINT fk_audit_event_case_id_exception_case FOREIGN KEY(case_id) REFERENCES exception_case (id) ON DELETE SET NULL,
	CONSTRAINT fk_audit_event_actor_user_id_app_user FOREIGN KEY(actor_user_id) REFERENCES app_user (id)
);
CREATE INDEX ix_audit_case_created ON audit_event (case_id, created_at);
CREATE INDEX ix_audit_recon_created ON audit_event (reconciliation_id, created_at);

CREATE TABLE case_evidence (
	id UUID NOT NULL,
	case_id UUID NOT NULL,
	kind VARCHAR(24) NOT NULL,
	conversation_evidence_id UUID,
	author_slack_id VARCHAR(32),
	excerpt TEXT NOT NULL,
	permalink TEXT,
	matched_on JSONB NOT NULL,
	score INTEGER,
	verified BOOLEAN NOT NULL,
	added_by UUID,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_case_evidence PRIMARY KEY (id),
	CONSTRAINT fk_case_evidence_case_id_exception_case FOREIGN KEY(case_id) REFERENCES exception_case (id) ON DELETE CASCADE,
	CONSTRAINT fk_case_evidence_conversation_evidence_id_conversation_evidence FOREIGN KEY(conversation_evidence_id) REFERENCES conversation_evidence (id) ON DELETE SET NULL,
	CONSTRAINT fk_case_evidence_added_by_app_user FOREIGN KEY(added_by) REFERENCES app_user (id)
);
CREATE INDEX ix_case_evidence_case ON case_evidence (case_id, created_at);

CREATE TABLE case_match_key (
	case_id UUID NOT NULL,
	key_type VARCHAR(16) NOT NULL,
	key_value VARCHAR(255) NOT NULL,
	CONSTRAINT pk_case_match_key PRIMARY KEY (case_id, key_type, key_value),
	CONSTRAINT fk_case_match_key_case_id_exception_case FOREIGN KEY(case_id) REFERENCES exception_case (id) ON DELETE CASCADE
);
CREATE INDEX ix_case_match_key_lookup ON case_match_key (key_type, key_value);

CREATE TABLE case_record (
	case_id UUID NOT NULL,
	payment_record_id UUID NOT NULL,
	CONSTRAINT pk_case_record PRIMARY KEY (case_id, payment_record_id),
	CONSTRAINT fk_case_record_case_id_exception_case FOREIGN KEY(case_id) REFERENCES exception_case (id) ON DELETE CASCADE,
	CONSTRAINT fk_case_record_payment_record_id_payment_record FOREIGN KEY(payment_record_id) REFERENCES payment_record (id) ON DELETE CASCADE
);

CREATE TABLE case_transaction (
	case_id UUID NOT NULL,
	bank_transaction_id UUID NOT NULL,
	active BOOLEAN DEFAULT 'true' NOT NULL,
	CONSTRAINT pk_case_transaction PRIMARY KEY (case_id, bank_transaction_id),
	CONSTRAINT fk_case_transaction_case_id_exception_case FOREIGN KEY(case_id) REFERENCES exception_case (id) ON DELETE CASCADE,
	CONSTRAINT fk_case_transaction_bank_transaction_id_bank_transaction FOREIGN KEY(bank_transaction_id) REFERENCES bank_transaction (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX one_open_case_per_txn ON case_transaction (bank_transaction_id) WHERE active;

CREATE TABLE listener_notification (
	id UUID NOT NULL,
	workspace_id UUID NOT NULL,
	case_id UUID NOT NULL,
	conversation_evidence_id UUID,
	score BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_listener_notification PRIMARY KEY (id),
	CONSTRAINT fk_listener_notification_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_listener_notification_case_id_exception_case FOREIGN KEY(case_id) REFERENCES exception_case (id) ON DELETE CASCADE,
	CONSTRAINT fk_listener_notification_conversation_evidence_id_conve_401a FOREIGN KEY(conversation_evidence_id) REFERENCES conversation_evidence (id) ON DELETE SET NULL
);
CREATE INDEX ix_listener_notification_case ON listener_notification (case_id, created_at);
CREATE INDEX ix_listener_notification_workspace ON listener_notification (workspace_id, created_at);

CREATE TABLE listener_suppression (
	case_id UUID NOT NULL,
	author_slack_id VARCHAR(32) NOT NULL,
	key_value VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_listener_suppression PRIMARY KEY (case_id, author_slack_id, key_value),
	CONSTRAINT fk_listener_suppression_case_id_exception_case FOREIGN KEY(case_id) REFERENCES exception_case (id) ON DELETE CASCADE
);
CREATE INDEX ix_suppression_lookup ON listener_suppression (case_id, author_slack_id, key_value);

CREATE TABLE resolution_proposal (
	id UUID NOT NULL,
	case_id UUID NOT NULL,
	reason_code VARCHAR(32) NOT NULL,
	narrative TEXT NOT NULL,
	evidence_ids JSONB NOT NULL,
	state VARCHAR(16) NOT NULL,
	proposed_by UUID,
	decided_by UUID,
	decided_at TIMESTAMP WITH TIME ZONE,
	case_version INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_resolution_proposal PRIMARY KEY (id),
	CONSTRAINT fk_resolution_proposal_case_id_exception_case FOREIGN KEY(case_id) REFERENCES exception_case (id) ON DELETE CASCADE,
	CONSTRAINT fk_resolution_proposal_proposed_by_app_user FOREIGN KEY(proposed_by) REFERENCES app_user (id),
	CONSTRAINT fk_resolution_proposal_decided_by_app_user FOREIGN KEY(decided_by) REFERENCES app_user (id)
);
CREATE INDEX ix_proposal_case_state ON resolution_proposal (case_id, state);

CREATE TABLE slack_outbox (
	id UUID NOT NULL,
	idempotency_key VARCHAR(255),
	available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	workspace_id UUID NOT NULL,
	case_id UUID,
	channel_id VARCHAR(32) NOT NULL,
	thread_ts VARCHAR(32),
	builder VARCHAR(64) NOT NULL,
	blocks JSONB NOT NULL,
	fallback_text TEXT NOT NULL,
	state VARCHAR(16) NOT NULL,
	attempts INTEGER NOT NULL,
	leased_until TIMESTAMP WITH TIME ZONE,
	message_ts VARCHAR(32),
	permalink TEXT,
	last_error TEXT,
	correlation_id VARCHAR(32),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	sent_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_slack_outbox PRIMARY KEY (id),
	CONSTRAINT uq_slack_outbox_idempotency_key UNIQUE (idempotency_key),
	CONSTRAINT fk_slack_outbox_workspace_id_workspace FOREIGN KEY(workspace_id) REFERENCES workspace (id) ON DELETE CASCADE,
	CONSTRAINT fk_slack_outbox_case_id_exception_case FOREIGN KEY(case_id) REFERENCES exception_case (id) ON DELETE SET NULL
);
CREATE INDEX ix_outbox_channel ON slack_outbox (channel_id, created_at);
CREATE INDEX ix_outbox_pending ON slack_outbox (state, created_at) WHERE state = 'PENDING';

CREATE TABLE transaction_match (
	id UUID NOT NULL,
	reconciliation_id UUID NOT NULL,
	bank_transaction_id UUID NOT NULL,
	payment_record_id UUID NOT NULL,
	score INTEGER NOT NULL,
	method VARCHAR(16) NOT NULL,
	state VARCHAR(16) NOT NULL,
	breakdown JSONB NOT NULL,
	decided_by UUID,
	decided_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_transaction_match PRIMARY KEY (id),
	CONSTRAINT one_match_per_txn UNIQUE (bank_transaction_id),
	CONSTRAINT one_match_per_record UNIQUE (payment_record_id),
	CONSTRAINT fk_transaction_match_reconciliation_id_reconciliation FOREIGN KEY(reconciliation_id) REFERENCES reconciliation (id) ON DELETE CASCADE,
	CONSTRAINT fk_transaction_match_bank_transaction_id_bank_transaction FOREIGN KEY(bank_transaction_id) REFERENCES bank_transaction (id) ON DELETE CASCADE,
	CONSTRAINT fk_transaction_match_payment_record_id_payment_record FOREIGN KEY(payment_record_id) REFERENCES payment_record (id) ON DELETE CASCADE,
	CONSTRAINT fk_transaction_match_decided_by_app_user FOREIGN KEY(decided_by) REFERENCES app_user (id)
);
CREATE INDEX ix_match_recon_state ON transaction_match (reconciliation_id, state);

-- PRD section 11: audit is append only, enforced by the database, not by code.
REVOKE UPDATE, DELETE ON audit_event FROM bankrecon_app;

-- Trigram index backing counterparty recall in the evidence search (PRD 6.4).
-- array_to_string(anyarray, text) is STABLE because some element types depend on
-- session settings. For text[] with a fixed separator, this wrapper is immutable.
CREATE OR REPLACE FUNCTION evidence_counterparty_text(text[]) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$ SELECT array_to_string($1, ' ') $$;
CREATE INDEX ix_evidence_counterparty_trgm ON conversation_evidence
  USING GIN (evidence_counterparty_text(counterparties) gin_trgm_ops);
