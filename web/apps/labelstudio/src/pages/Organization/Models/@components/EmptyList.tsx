import { Button } from "@humansignal/ui";
import { cn } from "apps/labelstudio/src/utils/bem";
import type { FC } from "react";
import "./EmptyList.prefix.css";
import { HeidiAi } from "apps/labelstudio/src/assets/images";

export const EmptyList: FC = () => {
  return (
    <div className={cn("empty-models-list").toClassName()}>
      <div className={cn("empty-models-list").elem("content").toClassName()}>
        <div className={cn("empty-models-list").elem("heidy").toClassName()}>
          <HeidiAi />
        </div>
        <div className={cn("empty-models-list").elem("title").toClassName()}>创建模型</div>
        <div className={cn("empty-models-list").elem("caption").toClassName()}>
          使用 LLM 构建高质量模型，自动标注你的数据
        </div>
        <Button aria-label="创建新模型">创建模型</Button>
      </div>
    </div>
  );
};
