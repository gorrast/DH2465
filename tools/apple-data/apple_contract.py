"""The standalone import contract. Shared summary tables are intentionally absent."""

VERSION = 3
CANONICAL_HEALTH = {
    'HKQuantityTypeIdentifierHeartRate': ('heart_rate', 'Heart rate', 'heart', 'count/min'),
    'HKQuantityTypeIdentifierRestingHeartRate': ('resting_heart_rate', 'Resting heart rate', 'heart', 'count/min'),
    'HKQuantityTypeIdentifierHeartRateVariabilitySDNN': ('hrv_sdnn', 'HRV (SDNN)', 'heart', 'ms'),
    'HKQuantityTypeIdentifierStepCount': ('steps', 'Steps', 'activity', 'count'),
}

