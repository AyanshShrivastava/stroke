import { createFileRoute, redirect } from "@tanstack/react-router";
import { createChat, loadChats } from "@/lib/keyboard-store";

export const Route = createFileRoute("/_authenticated/chat/")({
  beforeLoad: () => {
    const first = loadChats()[0] ?? createChat();
    throw redirect({ to: "/chat/$chatId", params: { chatId: first.id }, replace: true });
  },
});
