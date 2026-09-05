"""
Streamlit 前端主界面

布局：
    - 登录：未登录时显示用户名密码登录表单
    - 侧边栏 (st.sidebar)：上传 PDF、查看知识库状态、重置知识库
    - 主区域：聊天模式切换 + 输入框 + 对话展示
"""

import streamlit as st
from api_client import get_status, upload_file, chat, agent_chat, reset, login, register


def render_login():
    """登录/注册界面：成功后写入 session_state。"""
    st.title("企业智能知识库 Agent")
    st.caption("基于 RAG + Agent 的企业知识库智能问答平台")
    st.write("")
    tab_login, tab_register = st.tabs(["登录", "注册"])

    with tab_login:
        username = st.text_input("用户名", key="login_username")
        password = st.text_input("密码", type="password", key="login_password")
        if st.button("登录", key="btn_login"):
            result = login(username, password)
            if result.get("token"):
                st.session_state.token = result["token"]
                st.session_state.username = result["username"]
                st.session_state.role = result["role"]
                st.rerun()
            else:
                st.error(result.get("error") or "登录失败")

    with tab_register:
        username = st.text_input("用户名（至少3位）", key="reg_username")
        password = st.text_input("密码（至少6位）", type="password", key="reg_password")
        if st.button("注册", key="btn_register"):
            result = register(username, password)
            if result.get("token"):
                st.session_state.token = result["token"]
                st.session_state.username = result["username"]
                st.session_state.role = result["role"]
                st.rerun()
            else:
                st.error(result.get("error") or "注册失败")


def render_sidebar():
    """侧边栏：文件上传 + 知识库状态 + 重置。"""
    token = st.session_state.get("token")
    st.sidebar.title("知识库管理")
    st.sidebar.write(f"当前用户：**{st.session_state.get('username')}**（{st.session_state.get('role')}）")
    if st.sidebar.button("退出登录"):
        for key in ("token", "username", "role"):
            st.session_state.pop(key, None)
        st.rerun()

    uploaded = st.sidebar.file_uploader("上传文档", type=["pdf", "txt"])
    if uploaded:
        try:
            result = upload_file(uploaded, token=token)
            if result.get("error"):
                st.sidebar.error(result["error"])
            else:
                st.sidebar.success(result.get("message", "上传成功"))
        except Exception as e:
            st.sidebar.error(f"上传失败:{e}")

    status = get_status()
    st.sidebar.write(f"已索引 {status.get('total_chunks', 0)} 个 chunk")

    since = st.sidebar.selectbox("重置范围", ["all", "2h", "12h", "24h"])
    if st.sidebar.button("重置知识库"):
        result = reset(since, token=token)
        if result.get("error"):
            st.sidebar.error(result["error"])
        else:
            st.sidebar.success(f"已删除:{result.get('deleted_chunks', 0)}个chunk")


def render_chat():
    """主聊天区：模式切换 + 输入 + 对话展示。"""
    token = st.session_state.get("token")
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("sources"):
                with st.expander("引用来源"):
                    for s in msg["sources"]:
                        st.markdown(f"- **{s.get('source', '未知来源')}**（相关度 {s.get('score', 0):.2f}）")
                        st.caption(s.get("preview") or s.get("text", "")[:200])
            if msg.get("tool_calls"):
                with st.expander("工具调用记录"):
                    st.json(msg["tool_calls"])

    with st.form(key="chat_input_form", clear_on_submit=True):
        col_mode, col_input, col_send = st.columns([1.5, 4.3, 0.8])
        with col_mode:
            mode = st.radio("模式", ["RAG 问答", "Agent 问答"], horizontal=True, label_visibility="collapsed", key="mode_radio")
        with col_input:
            prompt = st.text_input("输入", key="prompt_input", placeholder="请输入你的问题...", label_visibility="collapsed")
        with col_send:
            submitted = st.form_submit_button("发送", use_container_width=True)

    if not (submitted and prompt):
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("思考中"):
            try:
                if mode == "RAG 问答":
                    result = chat(prompt, token=token)
                    answer = result.get("answer") or result.get("error") or "接口未返回 answer"
                    sources = result.get("sources", [])
                    st.write(answer)
                    if sources:
                        with st.expander("引用来源"):
                            for s in sources:
                                st.markdown(f"- **{s.get('source', '未知来源')}**（相关度 {s.get('score', 0):.2f}）")
                                st.caption(s.get("preview") or s.get("text", "")[:200])
                    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources})
                else:
                    result = agent_chat(prompt, token=token)
                    answer = result.get("answer") or result.get("error") or "接口未返回 answer"
                    tool_calls = result.get("tool_calls", [])
                    st.write(answer)
                    if tool_calls:
                        with st.expander("工具调用记录"):
                            st.json(tool_calls)
                    st.session_state.messages.append({"role": "assistant", "content": answer, "tool_calls": tool_calls})
            except Exception as e:
                st.error(f"请求失败{e}")


def inject_css():
    """注入 DeepSeek 风格自定义样式。"""
    st.markdown("""
    <style>
        /* 隐藏 Streamlit 默认菜单、页脚，界面更干净（保留顶栏以保留侧边栏折叠按钮） */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}

        /* 全局字体 */
        html, body, [class*="css"] {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
        }

        /* 主标题颜色 */
        h1 {
            color: #4D6BFE;
            font-weight: 700;
        }

        /* 聊天气泡圆角 + 阴影 */
        [data-testid="stChatMessage"] {
            border-radius: 12px;
            padding: 12px 16px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
        }

        /* 侧边栏分隔线 */
        [data-testid="stSidebar"] {
            border-right: 1px solid #E5E7EB;
        }
    </style>
    """, unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="企业知识库 Agent", page_icon="🤖", layout="wide")
    inject_css()
    if "token" not in st.session_state:
        render_login()
        return
    st.title("企业智能知识库 Agent 平台")
    render_sidebar()
    render_chat()


if __name__ == "__main__":
    main()
