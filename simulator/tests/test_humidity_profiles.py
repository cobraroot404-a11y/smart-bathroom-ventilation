from simulator.humidity_profiles import (
    generate_shower_profile,
    generate_steady_profile,
    inject_invalid_burst,
)


def test_shower_profile_is_deterministic_for_same_seed():
    a = generate_shower_profile(600, 5, seed=7)
    b = generate_shower_profile(600, 5, seed=7)
    assert [s.humidity_percent for s in a] == [s.humidity_percent for s in b]


def test_shower_profile_different_seed_differs():
    a = generate_shower_profile(600, 5, seed=1)
    b = generate_shower_profile(600, 5, seed=2)
    assert [s.humidity_percent for s in a] != [s.humidity_percent for s in b]


def test_shower_profile_rises_then_falls():
    samples = generate_shower_profile(
        total_seconds=600, sample_interval_seconds=5, seed=3, noise_amplitude_percent=0.0,
    )
    values = [s.humidity_percent for s in samples]
    peak_index = values.index(max(values))
    assert peak_index > 0
    assert values[peak_index] > values[0]  # rose from baseline
    assert values[-1] < values[peak_index]  # decayed from peak


def test_shower_profile_values_stay_in_valid_range():
    samples = generate_shower_profile(600, 5, seed=11)
    for s in samples:
        assert 0.0 <= s.humidity_percent <= 100.0


def test_steady_profile_is_constant():
    samples = generate_steady_profile(60, 5, humidity_percent=72.0)
    assert all(s.humidity_percent == 72.0 for s in samples)
    assert all(s.valid for s in samples)


def test_inject_invalid_burst_marks_window_invalid():
    samples = generate_steady_profile(60, 5, humidity_percent=50.0)
    marked = inject_invalid_burst(samples, start_seconds=20, duration_seconds=15)
    for s in marked:
        if 20 <= s.time_seconds < 35:
            assert s.valid is False
        else:
            assert s.valid is True


def test_inject_invalid_burst_does_not_mutate_input():
    samples = generate_steady_profile(30, 5, humidity_percent=50.0)
    inject_invalid_burst(samples, start_seconds=0, duration_seconds=10)
    assert all(s.valid for s in samples)
