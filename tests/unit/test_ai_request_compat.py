from src.services.ai_request_compat import (
    extract_max_tokens_cap,
    is_json_output_unsupported_error,
    is_max_tokens_out_of_range_error,
    is_responses_api_unsupported_error,
    is_temperature_unsupported_error,
    remove_temperature_param,
)


def test_is_temperature_unsupported_error_detects_unsupported_message():
    err = Exception("temperature is not supported by this gateway")
    assert is_temperature_unsupported_error(err) is True


def test_remove_temperature_param_removes_only_temperature():
    params = {"model": "x", "temperature": 0.5, "max_output_tokens": 128}
    result = remove_temperature_param(params)

    assert "temperature" not in result
    assert result["model"] == "x"
    assert result["max_output_tokens"] == 128


def test_is_responses_api_unsupported_error_detects_gemini_plain_404():
    class _Resp:
        text = ""

    class _Err(Exception):
        status_code = 404
        body = ""
        response = _Resp()

        def __str__(self):
            return "Error code: 404"

    assert is_responses_api_unsupported_error(_Err()) is True


# -- is_json_output_unsupported_error tests --


def test_json_output_error_detected_via_body_param_response_format():
    """Vercel AI Gateway returns 400 with param='response_format'."""

    class _Err(Exception):
        body = {
            "message": "Invalid input",
            "type": "invalid_request_error",
            "param": "response_format",
            "code": "invalid_request_error",
        }

    assert is_json_output_unsupported_error(_Err()) is True


def test_json_output_error_detected_via_body_param_response_format_type():
    class _Err(Exception):
        body = {
            "message": "Invalid input",
            "param": "response_format.type",
        }

    assert is_json_output_unsupported_error(_Err()) is True


def test_json_output_error_detected_via_legacy_string_matching():
    err = Exception(
        "response_format.type is not supported by this model"
    )
    assert is_json_output_unsupported_error(err) is True


def test_json_output_error_not_triggered_by_unrelated_400():
    class _Err(Exception):
        body = {
            "message": "Invalid input",
            "param": "messages",
        }

    assert is_json_output_unsupported_error(_Err()) is False


def test_json_output_error_not_triggered_without_body():
    err = Exception("some random 400 error")
    assert is_json_output_unsupported_error(err) is False


class FakeAPIError(Exception):
    pass


def test_is_max_tokens_out_of_range_error_matches_zhipu_style():
    err = FakeAPIError(
        "Error code: 400 - {'error': {'code': '1210', 'message': 'max_tokens参数非法：限制数值范围[1,1024]'}}"
    )
    assert is_max_tokens_out_of_range_error(err) is True
    assert extract_max_tokens_cap(err) == 1024


def test_is_max_tokens_out_of_range_error_ignores_other_errors():
    assert is_max_tokens_out_of_range_error(FakeAPIError("temperature not supported")) is False
    assert is_max_tokens_out_of_range_error(FakeAPIError("connection error")) is False
    # 提到 max_tokens 但无范围/限制语义 -> 不匹配
    assert is_max_tokens_out_of_range_error(FakeAPIError("max_tokens too small")) is False


def test_extract_max_tokens_cap_variants():
    assert extract_max_tokens_cap(FakeAPIError("max_tokens范围[1, 4096]")) == 4096
    assert extract_max_tokens_cap(FakeAPIError("max_tokens exceeds maximum allowed value 2048")) == 2048
    assert extract_max_tokens_cap(FakeAPIError("max_tokens bad but no numbers")) is None
