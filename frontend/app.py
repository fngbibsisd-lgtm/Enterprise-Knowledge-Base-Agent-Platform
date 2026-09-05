"""
Streamlit 前端主界面

布局：
    - 侧边栏 (st.sidebar)：上传 PDF、查看知识库状态、重置知识库
    - 主区域：聊天模式切换 + 输入框 + 对话展示
"""

import streamlit as st
from api_client import get_status, upload_file, chat, agent_chat, reset


def render_sidebar():
    """侧边栏：文件上传 + 知识库状态 + 重置。"""
    st.sidebar.title("知识库管理")
    uploaded=st.sidebar.file_uploader("上传文档", type=["pdf","txt"])
    if uploaded:
        try:
            result=upload_file(uploaded)
            if result.get("error"):
                st.sidebar.error(result["error"])
            else:
                st.sidebar.success(result.get("message","上传成功"))
        except Exception as e:
            st.sidebar.error(f"上传失败:{e}")
    status=get_status()
    st.sidebar.write(f"已索引{status.get('total_chunks',0)}个chunk")
    since=st.sidebar.selectbox("重置范围",["all","2h","12h","24h"])
    if st.sidebar.button("重置知识库"):
        result=reset(since)
        st.sidebar.success(f"已删除:{result.get('deleted_chunks',0)}个chunk")




def render_chat():
    """主聊天区：模式切换 + 输入 + 对话展示。"""
    mode=st.radio("问答模式",["RAG 问答","Agent 问答"],horizontal=True)
    if "messages" not in st.session_state:
        st.session_state.messages= []
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if msg.get("sources"):
                with st.expander("引用来源"):
                    for s in msg["sources"]:
                        st.markdown(f"- **{s.get('source','未知来源')}**(相关度  {s.get('score',0):.2f})")
                        st.caption(s.get("preview") or s.get("text","")[:200])
            if msg.get("tool_calls"):
                with st.expander("工具调用记录"):
                    st.json(msg["tool_calls"])
    prompt=st.chat_input("请输入你的问题...")
    if not prompt:
        return
    st.session_state.messages.append({"role":"user","content":prompt})
    with st.chat_message("user"):
        st.write(prompt)
    with st.chat_message("assistant"):
        with st.spinner("思考中"):
            try:
                if mode=="RAG 问答":
                    result=chat(prompt)
                    answer=result.get("answer","接口未返回 answer")
                    sources=result.get("sources",[])
                    st.write(answer)
                    if sources:
                        with st.expander("引用来源"):
                            for s in sources:
                                st.markdown(f"-**{s.get('source','未知来源')}** (相关度  {s.get('score',0):.2f})")
                                st.caption(s.get("preview") or s.get("text","")[:200])
                    st.session_state.messages.append({"role":"assistant","content":answer,"sources":sources})
                else:
                    result=agent_chat(prompt)
                    answer=result.get("answer","接口未返回 answer")
                    tool_calls=result.get("tool_calls",[])
                    st.write(answer)
                    if tool_calls:
                        with st.expander("工具调用记录"):
                            st.json(tool_calls)
                    st.session_state.messages.append({"role":"assistant","content":answer,"tool_calls":tool_calls})
            except Exception as e:
                st.error(f"请求失败{e}")





def main():
    st.set_page_config(page_title="企业知识库 Agent", page_icon="🤖", layout="wide")
    st.title("企业智能知识库 Agent 平台")
    render_sidebar()
    render_chat()


if __name__ == "__main__":
    main()
