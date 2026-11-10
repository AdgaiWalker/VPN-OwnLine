import type { PropsWithChildren } from "react";
import * as Dialog from "@radix-ui/react-dialog";

export function WebDialog({
  open,
  onOpenChange,
  title,
  children,
}: PropsWithChildren<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
}>) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="web-dialog-overlay" />
        <Dialog.Content className="web-dialog" aria-describedby={undefined}>
          <Dialog.Title className="web-dialog-title">{title}</Dialog.Title>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
