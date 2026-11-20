import pytest
from inventree_workshop import logic


class TestRunsFor:
    def test_exact_multiple(self):
        assert logic.runs_for(40, 20) == 2

    def test_rounds_up(self):
        assert logic.runs_for(41, 20) == 3
        assert logic.runs_for(1, 20) == 1

    def test_nothing_needed(self):
        assert logic.runs_for(0, 20) == 0
        assert logic.runs_for(-5, 20) == 0

    def test_float_noise_does_not_add_a_run(self):
        assert logic.runs_for(0.1 * 3 * 10, 3) == 1

    def test_needs_a_yield(self):
        with pytest.raises(ValueError):
            logic.runs_for(10, 0)


def suggest(**changes):
    values = {
        'stock': 0.0,
        'incoming': 0.0,
        'demand': 0.0,
        'minimum': 0.0,
        'restock_to': None,
        'per_run': 20.0,
    }
    values.update(changes)

    return logic.suggest(**values)


class TestSuggest:
    def test_nothing_when_there_is_enough(self):
        result = suggest(stock=50, minimum=40)
        assert result['runs'] == 0 and result['reason'] is None

    def test_at_the_minimum_is_enough(self):
        assert suggest(stock=40, minimum=40)['runs'] == 0

    def test_below_the_minimum(self):
        result = suggest(stock=10, minimum=40)
        assert result['runs'] == 2
        assert result['quantity'] == 40
        assert result['shortfall'] == 30
        assert result['reason'] == logic.REASON_LOW_STOCK

    def test_cuts_up_to_the_level(self):
        result = suggest(stock=10, minimum=40, restock_to=200)
        assert result['target'] == 200
        assert result['runs'] == 10

    def test_level_below_the_minimum_is_ignored(self):
        assert suggest(stock=10, minimum=40, restock_to=20)['target'] == 40

    def test_level_does_not_trigger_by_itself(self):
        assert suggest(stock=50, minimum=40, restock_to=200)['runs'] == 0

    def test_open_jobs_count_as_incoming(self):
        assert suggest(stock=10, incoming=40, minimum=40)['runs'] == 0

    def test_demand_of_build_orders(self):
        result = suggest(stock=50, demand=120, minimum=40)
        assert result['projected'] == -70
        assert result['runs'] == 6
        assert result['reason'] == logic.REASON_BUILD_DEMAND

    def test_demand_without_a_minimum(self):
        result = suggest(stock=10, demand=25)
        assert result['runs'] == 1 and result['reason'] == logic.REASON_BUILD_DEMAND

    def test_low_stock_wins_as_the_reason(self):
        assert suggest(stock=10, demand=5, minimum=40)['reason'] == logic.REASON_LOW_STOCK

    def test_no_minimum_no_demand(self):
        assert suggest()['runs'] == 0


def summarise(**changes):
    values = {
        'quantity': 40.0,
        'completed': 0.0,
        'per_run': 20.0,
        'bookings': [],
        'build_state': 'active',
        'closed': False,
    }
    values.update(changes)

    return logic.summarise(**values)


class TestSummarise:
    def test_new_job(self):
        state = summarise()
        assert state['state'] == logic.OPEN
        assert state['runs_planned'] == 2 and state['runs_left'] == 2 and state['runs_done'] == 0
        assert state['can_book'] and state['can_cancel'] and not state['can_close']

    def test_part_cut(self):
        state = summarise(completed=18, bookings=[{'good': 18, 'runs': 1}])
        assert state['state'] == logic.PARTIAL
        assert state['remaining'] == 22
        assert state['runs_left'] == 2
        assert state['rejected'] == 2
        assert state['can_book'] and state['can_close'] and not state['can_cancel']

    def test_a_run_of_rejects_only(self):
        state = summarise(bookings=[{'good': 0, 'runs': 1}])
        assert state['state'] == logic.PARTIAL
        assert state['rejected'] == 20
        assert state['can_cancel'] and not state['can_close']

    def test_everything_booked_but_still_open(self):
        state = summarise(completed=40, bookings=[{'good': 40, 'runs': 2}])
        assert state['state'] == logic.PARTIAL
        assert state['remaining'] == 0 and state['runs_left'] == 0
        assert state['can_close']

    def test_parts_completed_outside_the_plugin(self):
        state = summarise(completed=20)
        assert state['state'] == logic.PARTIAL and state['can_close'] and not state['can_cancel']

    def test_more_than_asked_for(self):
        state = summarise(quantity=20, completed=35, bookings=[{'good': 15, 'runs': 1}, {'good': 20, 'runs': 1}])
        assert state['remaining'] == 0 and state['rejected'] == 5

    def test_closed_by_the_plugin_while_the_build_order_completes(self):
        state = summarise(completed=18, bookings=[{'good': 18, 'runs': 1}], closed=True)
        assert state['state'] == logic.DONE
        assert not state['can_book'] and not state['can_close'] and not state['can_cancel']
        assert state['runs_left'] == 0

    def test_complete(self):
        assert summarise(completed=40, build_state='complete')['state'] == logic.DONE

    def test_cancelled(self):
        state = summarise(build_state='cancelled')
        assert state['state'] == logic.CANCELLED and not state['can_book']

    def test_cancelled_wins_over_closed(self):
        assert summarise(build_state='cancelled', closed=True)['state'] == logic.CANCELLED

    def test_yield_of_zero_does_not_break(self):
        assert summarise(per_run=0)['runs_planned'] == 40


class TestCheckBooking:
    def test_fine(self):
        assert logic.check_booking(18, 1, 20) is None
        assert logic.check_booking(0, 1, 20) is None
        assert logic.check_booking('20', '1', 20) is None
        assert logic.check_booking(40, 2, 20) is None

    def test_more_than_the_runs_give(self):
        message = logic.check_booking(21, 1, 20)
        assert message and '1 run of 20' in message

    def test_needs_a_run(self):
        assert logic.check_booking(5, 0, 20)
        assert logic.check_booking(5, -1, 20)
        assert logic.check_booking(5, 1.5, 20)

    def test_whole_parts(self):
        assert logic.check_booking(2.5, 1, 20)
        assert logic.check_booking(-1, 1, 20)

    def test_not_numbers(self):
        assert logic.check_booking(None, 1, 20)
        assert logic.check_booking('many', 1, 20)


class TestMaterial:
    def test_per_run(self):
        assert logic.material_for(0.05, 1, 20) == 1
        assert logic.material_for(0.05, 3, 20) == 3

    def test_awkward_fraction(self):
        assert logic.material_for(1 / 7, 2, 7) == 2

    def test_never_negative(self):
        assert logic.material_for(-1, 1, 20) == 0
        assert logic.material_for(0.05, 0, 20) == 0


class TestSplitStock:
    def test_from_the_first_item(self):
        assert logic.split_stock(1, [('a', 4), ('b', 6)]) == ([('a', 1)], 0.0)

    def test_across_items(self):
        assert logic.split_stock(5, [('a', 4), ('b', 6)]) == ([('a', 4), ('b', 1)], 0.0)

    def test_skips_empty_items(self):
        assert logic.split_stock(2, [('a', 0), ('b', 6)]) == ([('b', 2)], 0.0)

    def test_short(self):
        taken, short = logic.split_stock(11, [('a', 4), ('b', 6)])
        assert taken == [('a', 4), ('b', 6)] and short == 1

    def test_no_stock(self):
        assert logic.split_stock(2, []) == ([], 2)

    def test_nothing_wanted(self):
        assert logic.split_stock(0, [('a', 4)]) == ([], 0.0)
