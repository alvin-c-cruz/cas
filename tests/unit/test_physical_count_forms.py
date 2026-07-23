from app.stock_adjustments.forms import PhysicalCountForm, StockAdjustmentForm


class TestPhysicalCountForm:
    def test_valid_data(self, app):
        with app.test_request_context():
            form = PhysicalCountForm(data={'count_date': '2026-07-23', 'notes': 'Q3 count'})
            assert form.validate() is True

    def test_missing_count_date_is_invalid(self, app):
        with app.test_request_context():
            form = PhysicalCountForm(data={'notes': 'no date'})
            assert form.validate() is False


class TestStockAdjustmentFormReasonChoices:
    def test_physical_count_is_not_a_manual_choice(self, app):
        with app.test_request_context():
            form = StockAdjustmentForm()
            values = [choice[0] for choice in form.reason_type.choices]
            assert 'physical_count' not in values
            assert 'correction' in values
            assert 'opening' in values


class TestReasonTypeDisplay:
    def test_physical_count_reason_renders_as_two_words(self, client, admin_user, branch_main,
                                                          product_moving_avg, login_user):
        from datetime import date
        from app import db
        from app.settings import AppSettings
        from app.stock_adjustments.models import StockAdjustment, StockAdjustmentLine

        AppSettings.set_setting('module_enabled:inventory', '1', updated_by='test')
        AppSettings.set_setting('module_enabled:stock_adjustments', '1', updated_by='test')
        from app.utils.cache_helpers import clear_module_config_cache
        clear_module_config_cache()

        login_user(client, 'admin', 'admin123')
        client.post('/select-branch', data={'branch_id': branch_main.id})

        adj = StockAdjustment(sa_number='SA-2026-07-9001', branch_id=branch_main.id,
                              adjustment_date=date(2026, 7, 23), reason_type='physical_count',
                              status='draft', created_by_id=admin_user.id)
        adj.lines.append(StockAdjustmentLine(product_id=product_moving_avg.id,
                                             quantity_delta=1, unit_cost=10))
        db.session.add(adj)
        db.session.commit()

        resp = client.get(f'/stock-adjustments/{adj.id}')
        assert b'Physical Count' in resp.data
        assert b'Physical_count' not in resp.data
