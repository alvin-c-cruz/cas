"""Unit tests for the optimistic-locking primitive (app/utils/concurrency.py).

The guard exists because every document edit route is a replace-all: it discards
the stored lines (and, for APV/CDV/CRV, the linked journal entry) and rebuilds
them from the submitted payload.  Two encoders on one draft therefore means the
second save silently destroys the first one's work.

`claim_version` must be a *conditional UPDATE*, not a read-then-compare: a plain
comparison happens outside the transaction (SQLAlchemy defers BEGIN until the
first write), so both racers read the same version, both pass, and both write.
"""
import pytest
from werkzeug.datastructures import MultiDict
from wtforms import Form

from app import db
from app.audit.models import AuditLog
from app.utils.concurrency import (
    RowVersioned,
    RowVersionFormMixin,
    claim_version,
    conflict_message,
    fresh_number_if_collision,
    submitted_version,
)

pytestmark = pytest.mark.unit


class _VersionedThing(RowVersioned, db.Model):
    """Throwaway model exercising the mixin in isolation."""
    __tablename__ = '_test_versioned_thing'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20))


class _VersionedForm(RowVersionFormMixin, Form):
    pass


class _NumberedThing(db.Model):
    """Throwaway model with a unique document-number-style column, exercising
    fresh_number_if_collision in isolation (SI/AP/CD/CR's shape, not JV's)."""
    __tablename__ = '_test_numbered_thing'

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False)


def _make_thing(name='alpha'):
    thing = _VersionedThing(name=name)
    db.session.add(thing)
    db.session.commit()
    return thing


class TestRowVersionedMixin:

    def test_new_row_starts_at_version_one(self, db_session):
        thing = _make_thing()
        assert thing.row_version == 1


class TestClaimVersion:

    def test_current_token_wins_and_increments(self, db_session):
        thing = _make_thing()

        assert claim_version(_VersionedThing, thing.id, 1) is True
        assert thing.row_version == 2, 'ORM attribute must not be left stale'

    def test_stale_token_is_rejected_and_row_unchanged(self, db_session):
        thing = _make_thing()
        claim_version(_VersionedThing, thing.id, 1)  # someone else saved

        assert claim_version(_VersionedThing, thing.id, 1) is False
        db.session.expire(thing, ['row_version'])
        assert thing.row_version == 2, 'a losing claim must not bump the version'

    def test_exactly_one_racer_wins_the_same_token(self, db_session):
        """The whole point: two requests holding token 1 -> one winner."""
        thing = _make_thing()

        first = claim_version(_VersionedThing, thing.id, 1)
        second = claim_version(_VersionedThing, thing.id, 1)

        assert [first, second] == [True, False]
        db.session.expire(thing, ['row_version'])
        assert thing.row_version == 2, 'version must advance exactly once'

    def test_missing_token_is_rejected(self, db_session):
        thing = _make_thing()
        assert claim_version(_VersionedThing, thing.id, None) is False

    def test_unknown_id_is_rejected(self, db_session):
        assert claim_version(_VersionedThing, 99999, 1) is False


class TestConflictMessage:

    def test_names_the_user_and_time_from_the_audit_log(self, db_session, admin_user):
        thing = _make_thing()
        db.session.add(AuditLog(
            module='_test_versioned_thing',
            action='update',
            record_id=thing.id,
            user_id=admin_user.id,
        ))
        db.session.commit()

        msg = conflict_message('_test_versioned_thing', thing.id)

        assert admin_user.full_name in msg
        assert 'NOT saved' in msg
        assert 'reload' in msg.lower()

    def test_degrades_gracefully_when_no_audit_row_exists(self, db_session):
        """log_audit swallows its own errors, so the row can be absent."""
        thing = _make_thing()

        msg = conflict_message('_test_versioned_thing', thing.id)

        assert 'another user' in msg
        assert 'NOT saved' in msg

    def test_ignores_audit_rows_for_other_records_and_actions(self, db_session, admin_user):
        thing = _make_thing()
        db.session.add(AuditLog(
            module='_test_versioned_thing', action='create',
            record_id=thing.id, user_id=admin_user.id,
        ))
        db.session.add(AuditLog(
            module='_test_versioned_thing', action='update',
            record_id=thing.id + 500, user_id=admin_user.id,
        ))
        db.session.commit()

        msg = conflict_message('_test_versioned_thing', thing.id)

        assert admin_user.full_name not in msg
        assert 'another user' in msg

    def test_message_carries_no_apostrophe(self, db_session):
        """Flash assertions compare raw bytes; Jinja escapes ' to &#39;."""
        assert "'" not in conflict_message('_test_versioned_thing', 1)


class TestSubmittedVersion:
    """The token must come from the raw POST body, never from form.<field>.data."""

    def test_reads_the_token_from_the_post_body(self, app):
        with app.test_request_context('/', method='POST', data={'row_version': '3'}):
            assert submitted_version() == 3

    def test_absent_token_is_none_so_claim_version_rejects(self, app):
        with app.test_request_context('/', method='POST', data={}):
            assert submitted_version() is None

    def test_non_numeric_token_is_none(self, app):
        with app.test_request_context('/', method='POST', data={'row_version': 'abc'}):
            assert submitted_version() is None

    def test_empty_token_is_none(self, app):
        with app.test_request_context('/', method='POST', data={'row_version': ''}):
            assert submitted_version() is None


class TestRowVersionFormMixin:

    def test_coerces_formdata_string_to_int(self):
        # formdata=MultiDict, never data= -- data= skips coercion entirely
        form = _VersionedForm(formdata=MultiDict({'row_version': '7'}))
        assert form.row_version.data == 7

    def test_missing_token_validates_but_yields_none(self):
        """Optional(), not InputRequired(): the same form class serves create.

        On a create GET the field has no data, so hidden_tag renders value="",
        the POST sends '', and InputRequired would invalidate every create.
        Absence is rejected in the edit route instead -- claim_version(None) is
        False -- so a missing token still fails CLOSED.
        """
        form = _VersionedForm(formdata=MultiDict({}))
        assert form.validate() is True
        assert form.row_version.data is None

    def test_empty_token_yields_none_so_the_route_rejects_it(self):
        form = _VersionedForm(formdata=MultiDict({'row_version': ''}))
        assert form.row_version.data is None

    def test_non_numeric_token_fails_validation(self):
        form = _VersionedForm(formdata=MultiDict({'row_version': 'abc'}))
        assert form.validate() is False

    def test_wtforms_falls_back_to_obj_which_is_why_we_never_read_field_data(self):
        """Pins the fail-open hole that `submitted_version()` exists to avoid.

        Every edit route builds `Form(obj=doc)`. A POST with no token would make
        form.row_version.data return the document's CURRENT version, so
        claim_version() would succeed and the guard would pass.
        """
        class _Doc:
            row_version = 7

        form = _VersionedForm(formdata=MultiDict({}), obj=_Doc())
        assert form.row_version.data == 7, 'WTForms obj fallback (documented, not a bug)'

    def test_field_is_hidden_so_hidden_tag_emits_it(self):
        """All 7 form.html call hidden_tag(); it emits HiddenInput-widget fields.

        Rendering it explicitly too would post the name twice and request.form
        would read the empty first copy -- invisible to pytest.
        """
        from wtforms.widgets import HiddenInput
        form = _VersionedForm(formdata=MultiDict({'row_version': '1'}))
        assert isinstance(form.row_version.widget, HiddenInput)


class TestFreshNumberIfCollision:
    """SI/AP/CD/CR's user-editable-serial variant: never silently substitute; the
    caller re-renders with the fresh suggestion, it does not auto-commit."""

    def test_no_collision_returns_none(self, db_session):
        assert fresh_number_if_collision(
            _NumberedThing, 'number', 'NEW-001', lambda: 'NEW-002'
        ) is None

    def test_collision_returns_a_fresh_number_without_touching_the_db(self, db_session):
        db_session.add(_NumberedThing(number='DUP-001'))
        db_session.commit()

        fresh = fresh_number_if_collision(
            _NumberedThing, 'number', 'DUP-001', lambda: 'DUP-002'
        )

        assert fresh == 'DUP-002'
        assert _NumberedThing.query.count() == 1, 'must not insert or mutate anything'
