"""Mode-helper and interface-contract tests (R-07 Wave 0)."""
import pytest
from app.settings import AppSettings

pytestmark = [pytest.mark.integration]


def _set(db_session, key, on):
    AppSettings.set_setting(key, '1' if on else '0')
    db_session.commit()


def test_available_modes_empty_by_default(db_session):
    from app.bill_of_materials import service
    assert service.available_manufacturing_modes() == []


def test_available_modes_reflects_settings(db_session):
    from app.bill_of_materials import service
    _set(db_session, 'manufacturing_discrete_enabled', True)
    modes = service.available_manufacturing_modes()
    assert ('discrete', service.MANUFACTURING_MODES[0][1]) in modes
    assert not any(v == 'process' for v, _ in modes)

    _set(db_session, 'manufacturing_process_enabled', True)
    modes = service.available_manufacturing_modes()
    assert {v for v, _ in modes} == {'discrete', 'process'}


def test_consume_materials_is_a_wave0_stub():
    from app.bill_of_materials import service
    with pytest.raises(NotImplementedError, match='R-03 slice 2'):
        service.consume_materials(source_document=None, lines=[])


def test_produce_finished_goods_is_a_wave0_stub():
    from app.bill_of_materials import service
    with pytest.raises(NotImplementedError, match='R-03 slice 2'):
        service.produce_finished_goods(source_document=None, product_id=1, quantity=1, unit_cost=1)
