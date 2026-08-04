import { useCallback, useState } from "react";
import { Button } from "@humansignal/ui";
import { useAPI } from "../../../providers/ApiProvider";
import { Typography } from "@humansignal/ui";

export const StartModelTraining = ({ backend }) => {
  const api = useAPI();
  const [response, setResponse] = useState(null);

  const onStartTraining = useCallback(
    async (backend) => {
      const res = await api.callApi("trainMLBackend", {
        params: {
          pk: backend.id,
        },
      });

      setResponse(res.response || {});
    },
    [api],
  );

  return (
    <div className="max-w-[680px]">
      <Typography size="small" className="text-neutral-content-subtler">
        你即将手动触发模型训练。此操作将根据 ML 后端中 train 方法的实现开始学习阶段。点击继续即可开始。
      </Typography>
      <Typography size="small" className="text-neutral-content-subtler mt-base mb-wide">
        *注意：当前界面没有内置的训练进度反馈机制。你需要通过模型自身的工具和环境来监控模型的训练过程。
      </Typography>

      {!response && (
        <Button
          onClick={() => {
            onStartTraining(backend);
          }}
        >
          开始训练
        </Button>
      )}

      {!!response && (
        <>
          <pre>请求已发送！</pre>
          <pre>响应：{JSON.stringify(response, null, 2)}</pre>
        </>
      )}
    </div>
  );
};
