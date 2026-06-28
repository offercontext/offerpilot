// Interview retrospective note — mirrors Go db.InterviewNote JSON tags.
export interface InterviewNote {
  id: number;
  application_id?: number;
  company: string;
  position: string;
  round: string;
  date: string;
  questions: string;
  self_reflection: string;
  difficulty_points: string;
  mood: string;
  created_at: string;
}

export interface CreateNoteInput {
  company?: string;
  position?: string;
  round?: string;
  date?: string;
  questions?: string;
  self_reflection?: string;
  difficulty_points?: string;
  mood?: string;
}