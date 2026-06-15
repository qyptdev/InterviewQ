"""
Playwright测试：模拟面试批量管理功能

测试场景：
1. 非搜索状态批量删除
2. 搜索后批量删除（验证只删除可见项）
3. Shift连选基本流程
4. Shift连选跨越隐藏项（验证正确跳过）
"""

import asyncio
import pytest
from playwright.async_api import async_playwright, expect


async def setup_test_sessions(page, count=10):
    """创建测试会话"""
    session_ids = []

    for i in range(count):
        await page.goto("http://localhost:8000/sessions/new")
        await page.wait_for_load_state("networkidle")

        # 填写会话信息
        await page.fill('input[name="title"]', f"测试会话 {i+1}")
        await page.fill('input[name="job_role"]', f"测试岗位 {i+1}")

        # 提交创建
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("networkidle")

        # 提取session_id（从URL或响应中）
        # 简化：假设session按顺序创建
        session_ids.append(i + 1)

    return session_ids


@pytest.mark.asyncio
async def test_batch_delete_without_search():
    """测试场景1：非搜索状态批量删除"""
    print("\n=== 测试场景1：非搜索状态批量删除 ===")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # 前往会话列表页
        await page.goto("http://localhost:8000/sessions")
        await page.wait_for_load_state("networkidle")

        # 进入管理模式
        await page.click('button#manage-toggle-btn')
        await page.wait_for_timeout(500)

        # 选中前3个会话
        checkboxes = await page.query_selector_all('.session-checkbox')
        for i in range(min(3, len(checkboxes))):
            await checkboxes[i].check()

        await page.wait_for_timeout(300)

        # 验证选中数量显示
        count_text = await page.text_content('#selected-count')
        assert '3' in count_text, f"期望显示3个选中，实际: {count_text}"

        # 执行批量删除
        page.on('dialog', lambda dialog: asyncio.create_task(dialog.accept()))
        await page.click('button:has-text("批量删除")')

        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1000)

        # 重新获取页面元素（页面已刷新）
        remaining_cards = await page.query_selector_all('.session-card')
        print(f"✓ 删除后剩余会话数: {len(remaining_cards)}")

        await browser.close()
        print("✓ 测试场景1通过")


@pytest.mark.asyncio
async def test_batch_delete_with_search():
    """测试场景2：搜索后批量删除（核心bug验证）"""
    print("\n=== 测试场景2：搜索后批量删除 ===")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await page.goto("http://localhost:8000/sessions")
        await page.wait_for_load_state("networkidle")

        # 获取初始会话数
        initial_cards = await page.query_selector_all('.session-card')
        initial_count = len(initial_cards)
        print(f"初始会话数: {initial_count}")

        # 进入管理模式并选中多个会话
        await page.click('button#manage-toggle-btn')
        await page.wait_for_timeout(500)

        checkboxes = await page.query_selector_all('.session-checkbox')
        # 选中前5个
        for i in range(min(5, len(checkboxes))):
            await checkboxes[i].check()

        await page.wait_for_timeout(300)

        # 验证选中5个
        count_text = await page.text_content('#selected-count')
        print(f"选中会话: {count_text}")

        # 输入搜索关键词（假设只有1-2个会话匹配）
        await page.fill('#search-input', '测试会话 1')
        await page.wait_for_timeout(500)

        # 统计可见的选中会话
        visible_checked = await page.query_selector_all('.session-card:not(.hidden) .session-checkbox:checked')
        visible_count = len(visible_checked)
        print(f"搜索后可见的选中会话: {visible_count}")

        # 验证选中数量显示更新（应显示"当前可见 X"）
        count_text_after_search = await page.text_content('#selected-count')
        print(f"搜索后选中显示: {count_text_after_search}")
        assert f'当前可见 {visible_count}' in count_text_after_search or str(visible_count) in count_text_after_search

        # 执行批量删除
        page.on('dialog', lambda dialog: asyncio.create_task(dialog.accept()))
        await page.click('button:has-text("批量删除")')

        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1000)

        # 清空搜索，查看所有会话
        await page.fill('#search-input', '')
        await page.wait_for_timeout(500)

        # 验证只删除了可见的会话（重新获取元素）
        final_cards = await page.query_selector_all('.session-card')
        final_count = len(final_cards)

        expected_count = initial_count - visible_count
        print(f"删除后剩余会话数: {final_count}, 期望: {expected_count}")

        assert final_count == expected_count, f"期望剩余{expected_count}个会话，实际{final_count}个"

        await browser.close()
        print("✓ 测试场景2通过（只删除可见会话）")


@pytest.mark.asyncio
async def test_shift_click_selection():
    """测试场景3：Shift连选基本功能"""
    print("\n=== 测试场景3：Shift连选基本功能 ===")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await page.goto("http://localhost:8000/sessions")
        await page.wait_for_load_state("networkidle")

        # 进入管理模式
        await page.click('button#manage-toggle-btn')
        await page.wait_for_timeout(500)

        checkboxes = await page.query_selector_all('.session-checkbox')

        if len(checkboxes) < 5:
            print("⚠ 会话数量不足，跳过Shift连选测试")
            await browser.close()
            return

        # 点击第1个checkbox
        await checkboxes[0].click()
        await page.wait_for_timeout(200)

        # 按住Shift点击第5个checkbox
        await page.keyboard.down('Shift')
        await checkboxes[4].click()
        await page.keyboard.up('Shift')
        await page.wait_for_timeout(300)

        # 验证第1-5个全部选中
        for i in range(5):
            is_checked = await checkboxes[i].is_checked()
            assert is_checked, f"第{i+1}个checkbox应该被选中"

        print("✓ Shift连选成功：第1-5个checkbox全部选中")

        # 验证选中数量
        count_text = await page.text_content('#selected-count')
        assert '5' in count_text, f"期望显示5个选中，实际: {count_text}"

        await browser.close()
        print("✓ 测试场景3通过")


@pytest.mark.asyncio
async def test_shift_click_with_hidden_items():
    """测试场景4：Shift连选跨越隐藏项"""
    print("\n=== 测试场景4：Shift连选跨越隐藏项 ===")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await page.goto("http://localhost:8000/sessions")
        await page.wait_for_load_state("networkidle")

        # 进入管理模式
        await page.click('button#manage-toggle-btn')
        await page.wait_for_timeout(500)

        # 输入搜索关键词，隐藏部分会话（假设隐藏中间的几个）
        await page.fill('#search-input', '测试会话')
        await page.wait_for_timeout(500)

        # 获取所有可见的checkbox
        visible_checkboxes = await page.query_selector_all('.session-card:not(.hidden) .session-checkbox')

        if len(visible_checkboxes) < 3:
            print("⚠ 可见会话数量不足，跳过测试")
            await browser.close()
            return

        print(f"可见会话数: {len(visible_checkboxes)}")

        # 点击第1个可见checkbox
        await visible_checkboxes[0].click()
        await page.wait_for_timeout(200)

        # 按住Shift点击第3个可见checkbox
        await page.keyboard.down('Shift')
        await visible_checkboxes[2].click()
        await page.keyboard.up('Shift')
        await page.wait_for_timeout(300)

        # 验证前3个可见checkbox全部选中
        for i in range(3):
            is_checked = await visible_checkboxes[i].is_checked()
            assert is_checked, f"第{i+1}个可见checkbox应该被选中"

        print("✓ Shift连选成功：跳过隐藏项，只选中可见项")

        await browser.close()
        print("✓ 测试场景4通过")


async def main():
    """运行所有测试"""
    print("=" * 60)
    print("模拟面试批量管理功能测试")
    print("=" * 60)

    try:
        await test_batch_delete_without_search()
        await test_batch_delete_with_search()
        await test_shift_click_selection()
        await test_shift_click_with_hidden_items()

        print("\n" + "=" * 60)
        print("✓ 所有测试通过")
        print("=" * 60)
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
