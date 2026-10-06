use studenthub;
select * from students;
INSERT INTO students
(
    name,
    email,
    phone,
    gender,
    course_id,
    date_of_birth,
    status
)
VALUES
(
    'Neha Kapoor',
    'neha@example.com',
    '9111122222',
    'Female',
    1,
    '2003-02-10',
    'Active'
);

ALTER TABLE students
ADD COLUMN address VARCHAR(255);