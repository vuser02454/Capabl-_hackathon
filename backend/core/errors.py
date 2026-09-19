"""Typed errors mapped to user-friendly API responses."""


class EcoSentinelError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidLocationError(EcoSentinelError):
    status_code = 404
    code = "INVALID_LOCATION"


class NoMonitoringDataError(EcoSentinelError):
    status_code = 404
    code = "NO_MONITORING_DATA"


class DataSourceError(EcoSentinelError):
    status_code = 502
    code = "DATA_SOURCE_ERROR"


class ProviderNotConfiguredError(DataSourceError):
    status_code = 503
    code = "PROVIDER_NOT_CONFIGURED"


class SensorDataUnavailableError(DataSourceError):
    status_code = 503
    code = "SENSOR_DATA_UNAVAILABLE"


class InvalidImageError(EcoSentinelError):
    status_code = 400
    code = "INVALID_IMAGE"


class AnalysisFailedError(EcoSentinelError):
    status_code = 500
    code = "ANALYSIS_FAILED"


class GeocodingError(DataSourceError):
    status_code = 502
    code = "GEOCODING_FAILED"


class UnauthorizedError(EcoSentinelError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(EcoSentinelError):
    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(EcoSentinelError):
    status_code = 404
    code = "NOT_FOUND"
