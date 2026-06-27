import { useMemo, useState } from 'react';
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  DragOverlay,
  type DragStartEvent,
  type DragEndEvent,
} from '@dnd-kit/core';
import { useQueryClient } from '@tanstack/react-query';
import { message } from 'antd';
import { updateApplication } from '@/services/applications';
import {
  KANBAN_COLUMNS,
  STATUS_LABELS,
  STATUS_COLORS,
} from '@/types/application';
import type { Application, ApplicationStatus } from '@/types/application';
import KanbanColumn from './KanbanColumn';
import KanbanCard from './KanbanCard';
import styles from './KanbanBoard.module.css';

interface KanbanBoardProps {
  applications: Application[];
}

export default function KanbanBoard({ applications }: KanbanBoardProps) {
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = useState<number | null>(null);

  const columns = useMemo(() => {
    const grouped = {} as Record<ApplicationStatus, Application[]>;
    for (const s of KANBAN_COLUMNS) grouped[s] = [];
    applications.forEach((app) => {
      if (grouped[app.status]) grouped[app.status].push(app);
    });
    for (const key of KANBAN_COLUMNS) {
      grouped[key].sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      );
    }
    return grouped;
  }, [applications]);

  const activeRecord = applications.find((a) => a.id === activeId) ?? null;

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  );

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as number);
  };

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveId(null);
    if (!over) return;

    const currentStatus = active.data.current?.status as ApplicationStatus;
    const newStatus = over.id as ApplicationStatus;
    if (currentStatus === newStatus) return;

    const appId = active.id as number;
    const newLabel = STATUS_LABELS[newStatus];
    const appsKey = ['applications'];
    const previousApps = queryClient.getQueryData<Application[]>(appsKey);

    // Optimistic update
    queryClient.setQueryData<Application[]>(appsKey, (old = []) =>
      old.map((app) => (app.id === appId ? { ...app, status: newStatus } : app))
    );

    const revert = async () => {
      queryClient.setQueryData(appsKey, previousApps);
      const app = previousApps?.find((a) => a.id === appId);
      if (app) {
        try {
          await updateApplication(appId, {
            company_name: app.company_name,
            position_name: app.position_name,
            job_url: app.job_url,
            status: app.status,
            notes: app.notes,
          });
        } catch {
          queryClient.invalidateQueries({ queryKey: ['applications'] });
        }
      }
    };

    try {
      const app = previousApps?.find((a) => a.id === appId);
      await updateApplication(appId, {
        company_name: app?.company_name ?? '',
        position_name: app?.position_name ?? '',
        job_url: app?.job_url ?? '',
        status: newStatus,
        notes: app?.notes ?? '',
      });
      message.success({
        content: (
          <span>
            已移至「{newLabel}」
            <a
              style={{ marginLeft: 12, fontWeight: 600 }}
              onClick={() => {
                message.destroy('kanban-move');
                revert();
              }}
            >
              撤销
            </a>
          </span>
        ),
        key: 'kanban-move',
        duration: 4,
      });
    } catch {
      queryClient.setQueryData(appsKey, previousApps);
      message.error('状态更新失败，请重试');
    }
  };

  const handleDragCancel = () => {
    setActiveId(null);
  };

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      <div className={styles.board}>
        {KANBAN_COLUMNS.map((status) => (
          <KanbanColumn
            key={status}
            status={status}
            label={STATUS_LABELS[status]}
            color={STATUS_COLORS[status]}
            cards={columns[status]}
            activeId={activeId}
          />
        ))}
      </div>
      <DragOverlay dropAnimation={null}>
        {activeRecord ? <KanbanCard record={activeRecord} overlay /> : null}
      </DragOverlay>
    </DndContext>
  );
}
