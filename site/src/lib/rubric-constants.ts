export const TOTAL_FACTOR_COUNT = 184;
export const TOTAL_CATEGORY_COUNT = 13;
export const CRITICAL_FACTOR_COUNT = 20;
export const CORE_FIVE_CATEGORIES = [1, 2, 3, 5, 8] as const;

// Letter grade thresholds
export const TVL_MINIMUM_A_USD = 100_000_000;
export const AGE_MINIMUM_A_MONTHS = 12;
export const YELLOW_CAP_A = 4;
export const YELLOW_CAP_B = 10;
export const YELLOW_TRIGGER_C = 11; // ≥ this yellow count → C even with 0 reds

// Cat 3 special rule (oracle & external deps)
// Single oracle gap (e.g. no circuit breaker) ≠ category-red; needs ≥2 red factors
export const CAT3_RED_THRESHOLD = 2;
