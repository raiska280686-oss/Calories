def calculate_bmr(sex: str, age: int, height: float, weight: float) -> float:
    base = 10 * weight + 6.25 * height - 5 * age
    return base + 5 if sex == "male" else base - 161


ACTIVITY_FACTORS = {
    1: 1.2,
    2: 1.375,
    3: 1.55,
    4: 1.725,
    5: 1.9,
}


def calculate_norm(
    sex: str,
    age: int,
    height: float,
    weight: float,
    activity: int,
) -> dict:
    bmr = calculate_bmr(sex, age, height, weight)
    tdee = bmr * ACTIVITY_FACTORS.get(activity, 1.2)
    return {"bmr": bmr, "tdee": tdee}
