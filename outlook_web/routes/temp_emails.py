from __future__ import annotations

from flask import Blueprint

from outlook_web.controllers import temp_emails as temp_emails_controller


def create_blueprint(csrf_exempt=None) -> Blueprint:
    """创建 temp_emails Blueprint（支持 CSRF 豁免）"""
    bp = Blueprint("temp_emails", __name__)

    # 定义路由处理函数
    handlers = [
        ("/api/temp-emails", temp_emails_controller.api_get_temp_emails, ["GET"]),
        (
            "/api/temp-emails/options",
            temp_emails_controller.api_get_temp_email_options,
            ["GET"],
        ),
        (
            "/api/temp-emails/generate",
            temp_emails_controller.api_generate_temp_email,
            ["POST"],
        ),
        (
            "/api/temp-emails/<path:email_addr>/extract-verification",
            temp_emails_controller.api_extract_temp_email_verification,
            ["GET"],
        ),
        (
            "/api/temp-emails/<path:email_addr>/verification",
            temp_emails_controller.api_get_temp_email_verification,
            ["GET"],
        ),
        (
            "/api/temp-emails/<path:email_addr>",
            temp_emails_controller.api_delete_temp_email,
            ["DELETE"],
        ),
        (
            "/api/temp-emails/<path:email_addr>/messages",
            temp_emails_controller.api_get_temp_email_messages,
            ["GET"],
        ),
        (
            "/api/temp-emails/<path:email_addr>/messages/<path:message_id>",
            temp_emails_controller.api_get_temp_email_message_detail,
            ["GET"],
        ),
        (
            "/api/temp-emails/<path:email_addr>/messages/<path:message_id>",
            temp_emails_controller.api_delete_temp_email_message,
            ["DELETE"],
        ),
        (
            "/api/temp-emails/<path:email_addr>/clear",
            temp_emails_controller.api_clear_temp_email_messages,
            ["DELETE"],
        ),
        (
            "/api/temp-emails/<path:email_addr>/refresh",
            temp_emails_controller.api_refresh_temp_email_messages,
            ["POST"],
        ),
    ]

    # 注册路由，如果提供了 csrf_exempt 则应用到所有路由
    for path, handler, methods in handlers:
        view_func = csrf_exempt(handler) if csrf_exempt else handler
        bp.add_url_rule(path, view_func=view_func, methods=methods)

    return bp
