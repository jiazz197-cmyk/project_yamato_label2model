import { IconClose } from "@humansignal/icons";
import { Button } from "../button/button";
import { useModalControls } from "./ModalPopup";

export const ModalCloseButton = () => {
  const modal = useModalControls();
  return (
    <Button
      look="string"
      className="!p-0 [&_svg]:!w-6 [&_svg]:!h-6"
      leading={<IconClose />}
      aria-label="关闭弹窗"
      onClick={() => modal?.hide()}
    />
  );
};
