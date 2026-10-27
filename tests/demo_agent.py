"""python -m tests.demo_agent：保留可试听产物的本地模拟服务验收。"""

import copy
import json
from pathlib import Path

from yoin.agent import run_agent
from yoin.config import ModelConfig
from yoin.model import ChatModel

from .agent_helpers import completion, function_call
from .fake_provider import LocalProvider


def main():
    root = Path(__file__).resolve().parents[1]
    first = json.loads((root / "templates" / "quiet_reading.recipe.json").read_text())
    revised = copy.deepcopy(first)
    revised["layers"][0]["volume"] = 0.36
    revised["layers"][1]["volume"] = 0.38
    revised["layers"][1]["distance"] = 0.85
    revised["layers"][2]["volume"] = 0.30
    explanation = ("这是本地脚本响应的技术演示。选择下载的水滴、后院鸟鸣和翻书素材，去掉持续噪声铺底与混响。"
                   "根据分析微调水滴音量，把鸟叫放得更远，翻页更轻。保留水滴作为主体的占比提示，供人工试听。")
    responses = [
        completion(function_call("render_and_analyze", {"recipe": first}, "draft")),
        completion(function_call("render_and_analyze", {"recipe": revised}, "revision")),
        completion(function_call("submit_recipe", {"recipe": revised, "explanation": explanation}, "submit")),
    ]
    with LocalProvider(responses) as provider:
        config = ModelConfig("local-demo-key", provider.url, "local-scripted-demo")
        model = ChatModel(config)
        try:
            result = run_agent("安静阅读，偶尔水滴、远处鸟叫、轻轻翻页，不要持续雨声", root, model.complete,
                               model_info=config.public_info())
        finally:
            model.close()
        print("本地兼容服务演示：使用脚本响应，不是实际大模型生成。")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
