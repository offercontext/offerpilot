package db

import (
	"database/sql"
	"time"
)

// ApplicationMaterialKit stores the selected/generated materials for an application.
type ApplicationMaterialKit struct {
	ID            int64     `json:"id"`
	ApplicationID int64     `json:"application_id"`
	ResumeID      *int64    `json:"resume_id,omitempty"`
	JDAnalysisID  *int64    `json:"jd_analysis_id,omitempty"`
	JDSnapshot    string    `json:"jd_snapshot"`
	Status        string    `json:"status"`
	ContentJSON   string    `json:"content_json"`
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}

func normalizeApplicationMaterialKit(k *ApplicationMaterialKit) {
	if k.Status == "" {
		k.Status = "draft"
	}
	if k.ContentJSON == "" {
		k.ContentJSON = "{}"
	}
}

// CreateApplicationMaterialKit inserts a material kit for an application.
func (db *Database) CreateApplicationMaterialKit(k *ApplicationMaterialKit) error {
	normalizeApplicationMaterialKit(k)
	now := time.Now()
	res, err := db.conn.Exec(
		`INSERT INTO application_material_kits (application_id, resume_id, jd_analysis_id, jd_snapshot, status, content_json, created_at, updated_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		k.ApplicationID, nullableInt64(k.ResumeID), nullableInt64(k.JDAnalysisID), k.JDSnapshot, k.Status, k.ContentJSON, now, now,
	)
	if err != nil {
		return err
	}
	k.ID, _ = res.LastInsertId()
	k.CreatedAt = now
	k.UpdatedAt = now
	return nil
}

func scanApplicationMaterialKit(scan func(dest ...interface{}) error) (*ApplicationMaterialKit, error) {
	var k ApplicationMaterialKit
	var resumeID sql.NullInt64
	var jdAnalysisID sql.NullInt64
	if err := scan(
		&k.ID,
		&k.ApplicationID,
		&resumeID,
		&jdAnalysisID,
		&k.JDSnapshot,
		&k.Status,
		&k.ContentJSON,
		&k.CreatedAt,
		&k.UpdatedAt,
	); err != nil {
		return nil, err
	}
	if resumeID.Valid {
		v := resumeID.Int64
		k.ResumeID = &v
	}
	if jdAnalysisID.Valid {
		v := jdAnalysisID.Int64
		k.JDAnalysisID = &v
	}
	return &k, nil
}

const applicationMaterialKitCols = `id, application_id, resume_id, jd_analysis_id, jd_snapshot, status, content_json, created_at, updated_at`

// GetApplicationMaterialKit retrieves a single material kit by ID.
func (db *Database) GetApplicationMaterialKit(id int64) (*ApplicationMaterialKit, error) {
	row := db.conn.QueryRow(`SELECT `+applicationMaterialKitCols+` FROM application_material_kits WHERE id = ?`, id)
	return scanApplicationMaterialKit(row.Scan)
}

// GetApplicationMaterialKitByApplication retrieves the material kit for an application.
func (db *Database) GetApplicationMaterialKitByApplication(applicationID int64) (*ApplicationMaterialKit, error) {
	row := db.conn.QueryRow(`SELECT `+applicationMaterialKitCols+` FROM application_material_kits WHERE application_id = ?`, applicationID)
	return scanApplicationMaterialKit(row.Scan)
}

// UpdateApplicationMaterialKit updates mutable fields for a material kit.
func (db *Database) UpdateApplicationMaterialKit(k *ApplicationMaterialKit) error {
	normalizeApplicationMaterialKit(k)
	now := time.Now()
	_, err := db.conn.Exec(
		`UPDATE application_material_kits
		 SET resume_id = ?, jd_analysis_id = ?, jd_snapshot = ?, status = ?, content_json = ?, updated_at = ?
		 WHERE id = ?`,
		nullableInt64(k.ResumeID), nullableInt64(k.JDAnalysisID), k.JDSnapshot, k.Status, k.ContentJSON, now, k.ID,
	)
	if err != nil {
		return err
	}
	k.UpdatedAt = now
	return nil
}
