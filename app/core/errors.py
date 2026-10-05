class MealAnalysisError(Exception):
    def __init__(self, status_code: int, detail: str, code: str = "analysis_failed"):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
